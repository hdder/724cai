from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import logging
from datetime import datetime
import os
import base64
import time
import uuid
import secrets
import random
import string
import threading
import schedule
import json
from apscheduler.schedulers.background import BackgroundScheduler
from database import (
    init_database, get_all_channels, save_message,
    get_channel_messages, get_stats, get_all_tokens,
    get_channel_by_token, add_token, delete_token, update_tokens,
    create_session, delete_session, subscribe_channels,
    get_user_subscriptions, set_current_channel, get_current_channel,
    get_subscribers_for_channel, get_unread_count, mark_messages_as_read,
    get_all_unread_counts,
    get_channel, create_channel, delete_channel, get_next_channel_id,
    get_all_categories, create_category, update_category, delete_category,
    get_user_by_email, get_user_by_id, create_user, update_user, delete_user,
    get_all_users, save_user_token, get_user_by_token, delete_user_token,
    save_verification_code, verify_code, check_code_send_limit, cleanup_old_sessions, DB_PATH,
    get_channels_latest_message_time, get_channels_latest_messages_batch,
    get_all_templates, get_template_by_id, create_template, update_template, delete_template,
    get_card_by_code, get_card_by_id, get_all_cards, generate_cards, delete_card,
    update_card_activation, get_user_cards,
    get_db_connection,
    get_push_settings, update_push_settings, get_active_tokens_for_push, switch_active_token,
    get_messages_list, update_message_doubao, get_channel_doubao_summary, get_message_by_id
)
from auth_utils import (
    simple_encrypt, simple_decrypt, generate_access_token,
    generate_refresh_token, verify_token, require_auth, require_admin,
    generate_verification_code
)
from config import (
    FLASK_HOST, FLASK_PORT, WEBSOCKET_PORT, FRONTEND_PORT,
    PUBLIC_IP, FLASK_URL, WEBSOCKET_URL, FRONTEND_URL,
    PUSH_API_URL, PUSH_SERVICE_URL, ADMIN_TOKEN, ADMIN_URL,
    config
)
from email_service import send_verification_code
 
def decrypt_client_password(encrypted_password):
    """
    解密客户端传输的密码
    加密步骤：1.字符串反转 2.ASCII+3 3.Base64编码
    解密步骤：1.Base64解码 2.ASCII-3 3.字符串反转
    """
    try:
        # 1. Base64 解码
        decoded = base64.b64decode(encrypted_password).decode()

        # 2. 对每个字符的 ASCII 码减去固定偏移量
        shifted = ''
        for i in range(len(decoded)):
            shifted += chr(ord(decoded[i]) - 3)

        # 3. 字符串反转回来
        password = shifted[::-1]

        return password
    except Exception as e:
        raise ValueError(f'密码解密失败: {str(e)}')


def filter_and_validate_content(content):
    """
    过滤消息内容中的文件标签，保留图片供AI分析，验证是否有有效内容

    Args:
        content: 原始消息内容

    Returns:
        str: 过滤后的内容，如果完全无效则返回None
    """
    import re

    # 保存原始内容用于判断是否有图片
    original_content = content

    # 只过滤文件资源标签，不过滤图片
    content = re.sub(r'\[.*?文件.*?\]\(.*?\)', '', content)
    content = re.sub(r'\[.*?附件.*?\]\(.*?\)', '', content)

    # 去除首尾空白
    content = content.strip()

    # 检查是否有图片或有效文本
    has_images = bool(re.search(r'!\[.*?\]\(.*?\)', original_content))
    has_text = bool(content)

    # 有图片或有文本都返回内容
    if has_images or has_text:
        return content if has_text else "[图片]"  # 纯图片消息返回占位符

    return None


def call_doubao_api_single(api_url, headers, model, img_url, text_prompt, attempt, max_retries):
    """单次调用豆包API（1图+1文）"""
    content_list = []

    # 添加图片
    if img_url:
        content_list.append({
            "type": "input_image",
            "image_url": img_url
        })

    # 添加文本
    content_list.append({
        "type": "input_text",
        "text": text_prompt
    })

    data = {
        "model": model,
        "input": [
            {
                "role": "user",
                "content": content_list
            }
        ]
    }

    logger.info(f"调用豆包API (尝试 {attempt + 1}/{max_retries})")
    response = requests.post(api_url, headers=headers, json=data, timeout=30)

    if response.status_code == 200:
        result = response.json()
        output_list = result.get('output', [])

        ai_content = ''
        for item in output_list:
            if item.get('type') == 'message':
                content_list_resp = item.get('content', [])
                if content_list_resp and len(content_list_resp) > 0:
                    ai_content = content_list_resp[0].get('text', '').strip()
                    break

        if not ai_content:
            logger.error(f"豆包API返回格式异常，未找到message内容")
            return None

        # 清理JSON
        if ai_content.startswith('```json'):
            ai_content = ai_content[7:]
        if ai_content.startswith('```'):
            ai_content = ai_content[3:]
        if ai_content.endswith('```'):
            ai_content = ai_content[:-3]
        ai_content = ai_content.strip()

        return ai_content
    else:
        logger.error(f"豆包API调用失败: {response.status_code}, {response.text}")
        return None


def call_doubao_api(content, token=None, timestamp=None, content_preview=None):
    """调用豆包AI API分析消息内容（支持多张图片，分多次调用）

    Args:
        content: 消息完整内容
        token: 可选，频道token（用于日志）
        timestamp: 可选，消息时间戳（用于日志）
        content_preview: 可选，消息内容预览（用于日志）
    """
    import re

    # 从配置对象动态读取
    api_key = config.DOUBAO_API_KEY
    api_url = config.DOUBAO_API_URL
    model = config.DOUBAO_MODEL
    prompt_template = config.DOUBAO_PROMPT

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    # 提取图片
    image_pattern = r'!\[([^\]]*)\]\(([^)]+)\)'
    images = re.findall(image_pattern, content)

    # 过滤有效图片
    valid_images = [(alt, url) for alt, url in images if url.lower().endswith(('.png', '.jpg', '.jpeg'))]

    # 清理文本
    cleaned_text = re.sub(image_pattern, '', content)
    cleaned_text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', cleaned_text)
    cleaned_text = re.sub(r'\n+', '\n', cleaned_text).strip()

    prompt = f"{prompt_template}\n\n消息内容：\n{cleaned_text}"

    # 合并所有结果的股票列表（去重）
    all_stocks = {}
    max_retries = 3

    # 如果有图片，逐个调用
    if valid_images:
        for idx, (alt, img_url) in enumerate(valid_images):
            for attempt in range(max_retries):
                try:
                    logger.info(f"处理图片 {idx + 1}/{len(valid_images)}: {img_url}")
                    ai_result = call_doubao_api_single(api_url, headers, model, img_url, prompt, attempt, max_retries)

                    if ai_result:
                        try:
                            parsed = json.loads(ai_result)
                            stock_list = parsed.get('stock_list', [])

                            # 去重合并（以stock_name为主键）
                            for stock in stock_list:
                                stock_name = stock.get('stock_name')
                                if stock_name and stock_name not in all_stocks:
                                    all_stocks[stock_name] = stock

                            logger.info(f"图片 {idx + 1} 识别到 {len(stock_list)} 只股票")
                            break  # 成功则跳出重试循环
                        except json.JSONDecodeError:
                            logger.error(f"图片 {idx + 1} 返回JSON无效")
                            if attempt < max_retries - 1:
                                time.sleep(1)
                                continue
                except Exception as e:
                    logger.error(f"图片 {idx + 1} 处理异常: {e}")
                    if attempt < max_retries - 1:
                        time.sleep(1)
                        continue
    else:
        # 没有图片，只调用一次（纯文本）
        for attempt in range(max_retries):
            try:
                ai_result = call_doubao_api_single(api_url, headers, model, None, prompt, attempt, max_retries)
                if ai_result:
                    try:
                        parsed = json.loads(ai_result)
                        stock_list = parsed.get('stock_list', [])
                        for stock in stock_list:
                            stock_name = stock.get('stock_name')
                            if stock_name and stock_name not in all_stocks:
                                all_stocks[stock_name] = stock
                        break
                    except json.JSONDecodeError:
                        logger.error("纯文本分析返回JSON无效")
                        if attempt < max_retries - 1:
                            time.sleep(1)
                            continue
            except Exception as e:
                logger.error(f"纯文本分析异常: {e}")
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue

    # 构建最终结果
    final_stock_list = list(all_stocks.values())
    result_json = json.dumps({"stock_list": final_stock_list}, ensure_ascii=False)

    # 日志
    log_parts = [f"豆包API调用完成，共识别 {len(final_stock_list)} 只股票"]
    if token:
        log_parts.append(f"Token: {token}")
    if timestamp:
        log_parts.append(f"时间: {timestamp}")
    if content_preview:
        preview = content_preview[:100] + ('...' if len(content_preview) > 100 else '')
        log_parts.append(f"内容: {preview}")

    logger.info(' | '.join(log_parts))
    return result_json


def call_siliconflow_api_single(api_url, headers, model, img_url, text_prompt, attempt, max_retries):
    """单次调用SiliconFlow API（1图+1文）"""
    content_list = []

    # 添加图片
    if img_url:
        content_list.append({
            "type": "image_url",
            "image_url": {
                "url": img_url
            }
        })

    # 添加文本
    content_list.append({
        "type": "text",
        "text": text_prompt
    })

    data = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": content_list
            }
        ],
        "max_tokens": 2000
    }

    logger.info(f"调用SiliconFlow API (尝试 {attempt + 1}/{max_retries})")
    response = requests.post(api_url, headers=headers, json=data, timeout=30)

    if response.status_code == 200:
        result = response.json()
        choices = result.get('choices', [])

        if choices and len(choices) > 0:
            ai_content = choices[0].get('message', {}).get('content', '').strip()

            if not ai_content:
                logger.error(f"SiliconFlow API返回内容为空")
                return None

            # 清理JSON
            if ai_content.startswith('```json'):
                ai_content = ai_content[7:]
            if ai_content.startswith('```'):
                ai_content = ai_content[3:]
            if ai_content.endswith('```'):
                ai_content = ai_content[:-3]
            ai_content = ai_content.strip()

            return ai_content
        else:
            logger.error(f"SiliconFlow API返回格式异常，未找到choices")
            return None
    else:
        logger.error(f"SiliconFlow API调用失败: {response.status_code}, {response.text}")
        return None


def call_siliconflow_api(content, token=None, timestamp=None, content_preview=None):
    """调用SiliconFlow AI API分析消息内容（支持多张图片，分多次调用）

    Args:
        content: 消息完整内容
        token: 可选，频道token（用于日志）
        timestamp: 可选，消息时间戳（用于日志）
        content_preview: 可选，消息内容预览（用于日志）
    """
    import re

    # 从配置对象动态读取
    api_key = config.SILICONFLOW_API_KEY
    api_url = config.SILICONFLOW_API_URL
    model = config.SILICONFLOW_MODEL
    prompt_template = config.SILICONFLOW_PROMPT

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    # 提取图片
    image_pattern = r'!\[([^\]]*)\]\(([^)]+)\)'
    images = re.findall(image_pattern, content)

    # 过滤有效图片
    valid_images = [(alt, url) for alt, url in images if url.lower().endswith(('.png', '.jpg', '.jpeg'))]

    # 清理文本
    cleaned_text = re.sub(image_pattern, '', content)
    cleaned_text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', cleaned_text)
    cleaned_text = re.sub(r'\n+', '\n', cleaned_text).strip()

    prompt = f"{prompt_template}\n\n消息内容：\n{cleaned_text}"

    # 合并所有结果的股票列表（去重）
    all_stocks = {}
    max_retries = 3

    # 如果有图片，逐个调用
    if valid_images:
        for idx, (alt, img_url) in enumerate(valid_images):
            for attempt in range(max_retries):
                try:
                    logger.info(f"处理图片 {idx + 1}/{len(valid_images)}: {img_url}")
                    ai_result = call_siliconflow_api_single(api_url, headers, model, img_url, prompt, attempt, max_retries)

                    if ai_result:
                        try:
                            parsed = json.loads(ai_result)
                            stock_list = parsed.get('stock_list', [])

                            # 去重合并（以stock_name为主键）
                            for stock in stock_list:
                                stock_name = stock.get('stock_name')
                                if stock_name and stock_name not in all_stocks:
                                    all_stocks[stock_name] = stock

                            logger.info(f"图片 {idx + 1} 识别到 {len(stock_list)} 只股票")
                            break  # 成功则跳出重试循环
                        except json.JSONDecodeError:
                            logger.error(f"图片 {idx + 1} 返回JSON无效")
                            if attempt < max_retries - 1:
                                time.sleep(1)
                                continue
                except Exception as e:
                    logger.error(f"图片 {idx + 1} 处理异常: {e}")
                    if attempt < max_retries - 1:
                        time.sleep(1)
                        continue
    else:
        # 没有图片，只调用一次（纯文本）
        for attempt in range(max_retries):
            try:
                ai_result = call_siliconflow_api_single(api_url, headers, model, None, prompt, attempt, max_retries)
                if ai_result:
                    try:
                        parsed = json.loads(ai_result)
                        stock_list = parsed.get('stock_list', [])
                        for stock in stock_list:
                            stock_name = stock.get('stock_name')
                            if stock_name and stock_name not in all_stocks:
                                all_stocks[stock_name] = stock
                        break
                    except json.JSONDecodeError:
                        logger.error("纯文本分析返回JSON无效")
                        if attempt < max_retries - 1:
                            time.sleep(1)
                            continue
            except Exception as e:
                logger.error(f"纯文本分析异常: {e}")
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue

    # 构建最终结果
    final_stock_list = list(all_stocks.values())
    result_json = json.dumps({"stock_list": final_stock_list}, ensure_ascii=False)

    # 日志
    log_parts = [f"SiliconFlow API调用完成，共识别 {len(final_stock_list)} 只股票"]
    if token:
        log_parts.append(f"Token: {token}")
    if timestamp:
        log_parts.append(f"时间: {timestamp}")
    if content_preview:
        preview = content_preview[:100] + ('...' if len(content_preview) > 100 else '')
        log_parts.append(f"内容: {preview}")

    logger.info(' | '.join(log_parts))
    return result_json


def analyze_message_with_doubao(message_id, content, token=None, timestamp=None):
    """在后台线程中调用豆包API分析消息

    Args:
        message_id: 消息ID
        content: 消息内容
        token: 可选，频道token（用于日志）
        timestamp: 可选，消息时间戳（用于日志）
    """
    def _analyze():
        try:
            # 调用豆包API，传递token、timestamp和content用于日志
            result = call_doubao_api(content, token=token, timestamp=timestamp, content_preview=content)
            # 更新数据库
            update_message_doubao(message_id, result)
            logger.info(f"消息 {message_id} 豆包AI分析完成: {result}")
        except Exception as e:
            logger.error(f"豆包AI分析失败 (消息ID: {message_id}): {e}")

    # 在后台线程中执行，不阻塞主进程
    thread = threading.Thread(target=_analyze, daemon=True)
    thread.start()


def analyze_message_with_siliconflow(message_id, content, token=None, timestamp=None):
    """在后台线程中调用SiliconFlow API分析消息

    Args:
        message_id: 消息ID
        content: 消息内容
        token: 可选，频道token（用于日志）
        timestamp: 可选，消息时间戳（用于日志）
    """
    def _analyze():
        try:
            # 调用SiliconFlow API，传递token、timestamp和content用于日志
            result = call_siliconflow_api(content, token=token, timestamp=timestamp, content_preview=content)
            # 更新数据库
            update_message_doubao(message_id, result)
            logger.info(f"消息 {message_id} SiliconFlow AI分析完成: {result}")
        except Exception as e:
            logger.error(f"SiliconFlow AI分析失败 (消息ID: {message_id}): {e}")

    # 在后台线程中执行，不阻塞主进程
    thread = threading.Thread(target=_analyze, daemon=True)
    thread.start()


def analyze_message(message_id, content, token=None, timestamp=None):
    """根据配置调用AI分析消息（支持doubao/siliconflow）

    Args:
        message_id: 消息ID
        content: 消息内容
        token: 可选，频道token（用于日志）
        timestamp: 可选，消息时间戳（用于日志）
    """
    provider = config.AI_PROVIDER

    if provider == 'siliconflow':
        analyze_message_with_siliconflow(message_id, content, token=token, timestamp=timestamp)
    else:  # 默认使用doubao
        analyze_message_with_doubao(message_id, content, token=token, timestamp=timestamp)



# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 初始化数据库
init_database()

app = Flask(__name__)

# 启用 CORS（生产安全版 + 性能最优）
# 支持本地开发 + 国内服务器 + Vercel前端 + HTTPS
ALLOWED_ORIGINS = [
    "http://111.228.8.17:8000",  # 当前前端 HTTP
    "https://111.228.8.17:8000",  # 当前前端 HTTPS
    "http://localhost:8000",      # 本地开发
    "https://724-cx.vercel.app",  # Vercel前端
    "https://www.724caixun.com",  # 自定义域名（如果有）
    "https://724caixun.com"       # 自定义域名（不带www）
]

CORS(app, resources={
    r"/api/*": {
        "origins": ALLOWED_ORIGINS,
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"],
        "max_age": 86400  # 预检缓存1天，性能最好
    },
    r"/admin/*": {
        "origins": ALLOWED_ORIGINS,
        "methods": ["POST", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"],
        "max_age": 86400
    },
    r"/push/*": {
        "origins": ALLOWED_ORIGINS,
        "methods": ["POST", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"],
        "max_age": 86400
    }
})

# 启动股票数据同步定时任务
scheduler = BackgroundScheduler()
try:
    from stock_sync import sync_stock_data

    # 每日凌晨3点执行
    scheduler.add_job(
        sync_stock_data,
        trigger='cron',
        hour=3,
        minute=0,
        id='daily_stock_sync'
    )

    scheduler.start()
    logger.info("✓ 股票数据同步定时任务已启动（每日凌晨3:00）")
except ImportError as e:
    logger.warning(f"无法导入stock_sync模块: {e}")
    logger.warning("股票同步定时任务未启动")

# Node.js 推送服务地址（从配置文件读取）
# PUSH_SERVICE_URL 已从 config 模块导入

# 图床上传配置
# 使用自定义图床服务
IMAGE_UPLOAD_URL = "https://api.gaotu.cn/v1/storage/upload"

# 头像备份目录
AVATAR_BACKUP_DIR = os.path.join(os.path.dirname(__file__), '..', 'avatars')

def upload_to_image_host(base64_data):
    """上传图片到图床并返回公网链接"""
    try:
        # 解码base64数据
        if ',' in base64_data:
            base64_data = base64_data.split(',')[1]

        # 解码为二进制数据
        image_data = base64.b64decode(base64_data)

        # 上传到自定义图床
        response = requests.post(
            IMAGE_UPLOAD_URL,
            files={'file': ('avatar.png', image_data)},
            timeout=30
        )

        if response.status_code == 200:
            result = response.json()
            if result.get('code') == 0:
                # 图床返回格式: {code: 0, data: {url: "https://..."}}
                url = result.get('data', {}).get('url')
                if url:
                    return url

        return None
    except Exception as e:
        logger.error(f"图床上传异常: {e}")
        return None

def save_avatar_backup(channel_id, base64_data):
    """保存头像到服务器本地备份"""
    try:
        # 确保备份目录存在
        os.makedirs(AVATAR_BACKUP_DIR, exist_ok=True)

        # 解码base64数据
        if ',' in base64_data:
            base64_data = base64_data.split(',')[1]

        image_data = base64.b64decode(base64_data)

        # 保存到本地，文件名为频道ID.png
        backup_path = os.path.join(AVATAR_BACKUP_DIR, f"{channel_id}.png")
        with open(backup_path, 'wb') as f:
            f.write(image_data)

        return True
    except Exception as e:
        logger.error(f"头像备份失败: {e}")
        return False

# ============ 图片上传 API ============

@app.route('/api/upload-image', methods=['POST'])
def upload_image_api():
    """上传图片到图床

    Request Body:
        image: base64 编码的图片数据（data:image/png;base64,...）

    Returns:
        {
            "success": true,
            "url": "https://image-host.com/xxx.png"
        }
    """
    try:
        data = request.json
        image_data = data.get('image', '')

        if not image_data:
            return jsonify({
                'success': False,
                'error': '图片数据不能为空'
            }), 400

        # 上传到图床
        uploaded_url = upload_to_image_host(image_data)

        if uploaded_url:
            return jsonify({
                'success': True,
                'url': uploaded_url
            })
        else:
            return jsonify({
                'success': False,
                'error': '图床上传失败，请稍后重试'
            }), 500

    except Exception as e:
        logger.error(f"上传图片API异常: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# ============ 标签管理 API ============

@app.route('/api/categories', methods=['GET'])
def get_categories_api():
    """获取所有标签

    Query Parameters:
        type: 标签类型，'public' 或 'private' 或 'all'，默认为 'public'
    """
    category_type = request.args.get('type', 'public')

    # 如果请求所有类型，则不传 type 参数
    if category_type == 'all':
        from database import get_db_connection
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, frequency, type FROM categories ORDER BY frequency DESC")
        rows = cursor.fetchall()
        conn.close()
        categories = [dict(row) for row in rows]
    else:
        categories = get_all_categories(category_type)

    return jsonify({
        'success': True,
        'categories': categories
    })

@app.route('/api/categories', methods=['POST'])
def add_category_api():
    """添加标签

    Request Body:
        name: 标签名称
        frequency: 频率 (0-100)
        type: 标签类型，'public' 或 'private'，默认为 'public'
    """
    try:
        data = request.json
        name = data.get('name', '').strip()
        frequency = data.get('frequency', 50)
        category_type = data.get('type', 'public')

        # 验证标签类型
        if category_type not in ['public', 'private']:
            return jsonify({'success': False, 'message': '标签类型必须是 public 或 private'}), 400

        if not name:
            return jsonify({'success': False, 'message': '标签名称不能为空'}), 400

        # 验证频率范围
        try:
            frequency = int(frequency)
            if frequency < 0 or frequency > 100:
                return jsonify({'success': False, 'message': '频率必须在0-100之间'}), 400
        except ValueError:
            return jsonify({'success': False, 'message': '频率必须是数字'}), 400

        category_id = create_category(name, frequency, category_type)
        if category_id:
            return jsonify({'success': True, 'message': '标签添加成功', 'id': category_id})
        else:
            return jsonify({'success': False, 'message': '添加标签失败'}), 500

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/categories', methods=['PUT'])
def update_category_api():
    """更新标签"""
    try:
        data = request.json
        category_id = data.get('id')

        if not category_id:
            return jsonify({'success': False, 'message': '标签ID不能为空'}), 400

        # 验证频率范围
        frequency = data.get('frequency')
        if frequency is not None:
            try:
                frequency = int(frequency)
                if frequency < 0 or frequency > 100:
                    return jsonify({'success': False, 'message': '频率必须在0-100之间'}), 400
            except ValueError:
                return jsonify({'success': False, 'message': '频率必须是数字'}), 400

        success = update_category(
            category_id,
            name=data.get('name'),
            frequency=frequency
        )

        if success:
            return jsonify({'success': True, 'message': '标签更新成功'})
        else:
            return jsonify({'success': False, 'message': '标签不存在'}), 404

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/categories/frequency', methods=['PUT'])
def update_category_frequency_api():
    """单独更新标签频率"""
    try:
        data = request.json
        category_id = data.get('id')
        frequency = data.get('frequency', 50)

        if not category_id:
            return jsonify({'success': False, 'message': '标签ID不能为空'}), 400

        # 验证频率范围
        try:
            frequency = int(frequency)
            if frequency < 0 or frequency > 100:
                return jsonify({'success': False, 'message': '频率必须在0-100之间'}), 400
        except ValueError:
            return jsonify({'success': False, 'message': '频率必须是数字'}), 400

        success = update_category(category_id, frequency=frequency)

        if success:
            return jsonify({'success': True, 'message': '频率更新成功'})
        else:
            return jsonify({'success': False, 'message': '标签不存在'}), 404

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/categories', methods=['DELETE'])
def delete_category_api():
    """删除标签"""
    try:
        category_id = request.args.get('id', '').strip()

        if not category_id:
            return jsonify({'success': False, 'message': '标签ID不能为空'}), 400

        if delete_category(category_id):
            return jsonify({'success': True, 'message': '标签删除成功'})
        else:
            return jsonify({'success': False, 'message': '标签不存在'}), 404

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# ============ 原有 API ============

@app.route('/push/send', methods=['POST', 'OPTIONS'])
def admin_send_message():
    """外部程序调用接口 - 兼容主流机器人格式"""
    # 处理 OPTIONS 预检请求
    if request.method == 'OPTIONS':
        response = jsonify({'code': 0, 'message': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        return response

    # 收集日志信息
    log_lines = []
    start_time = datetime.now()

    # 获取 channel_token
    channel_token = request.args.get('channel_token')

    log_lines.append(f"{'='*60}")
    log_lines.append(f"收到推送请求")
    log_lines.append(f"请求来源: {request.remote_addr}")
    log_lines.append(f"Channel Token: {channel_token}")
    log_lines.append(f"请求体: {request.get_data(as_text=True)}")

    if not channel_token:
        log_lines.append(f"✗ 请求失败: 缺少 channel_token 参数")
        logger.info('\n'.join(log_lines))
        return jsonify({
            'code': 401,
            'message': '缺少 channel_token 参数'
        }), 401

    # 从数据库验证 token
    channel_id = get_channel_by_token(channel_token)

    if not channel_id:
        log_lines.append(f"✗ 请求失败: 无效的 channel_token: {channel_token}")
        logger.info('\n'.join(log_lines))
        return jsonify({
            'code': 401,
            'message': f'无效的 channel_token: {channel_token}'
        }), 401

    log_lines.append(f"Token 验证成功, 频道ID: {channel_id}")

    # 解析请求体
    try:
        data = request.json

        if not data:
            log_lines.append(f"✗ 请求失败: 请求体为空")
            logger.info('\n'.join(log_lines))
            return jsonify({
                'code': 400,
                'message': '请求体不能为空'
            }), 400

        # 验证消息格式
        msgtype = data.get('msgtype')

        log_lines.append(f"消息类型: {msgtype}")

        # 支持 markdown 和 markdown_v2 两种格式
        if msgtype not in ['markdown', 'markdown_v2']:
            log_lines.append(f"✗ 请求失败: 不支持的 msgtype: {msgtype}")
            logger.info('\n'.join(log_lines))
            return jsonify({
                'code': 400,
                'message': f'不支持的 msgtype: {msgtype}，支持 markdown 和 markdown_v2'
            }), 400

        # 根据不同格式解析内容
        if msgtype == 'markdown':
            markdown = data.get('markdown', {})
            title = markdown.get('title', '')  # 默认为空字符串
            text = markdown.get('text', '')
        else:  # markdown_v2
            markdown_v2 = data.get('markdown_v2', {})
            # markdown_v2 格式通常只有 content 字段
            title = markdown_v2.get('title', '')  # 默认为空字符串
            text = markdown_v2.get('content', '')

        log_lines.append(f"消息标题: {title if title else '(无标题)'}")
        log_lines.append(f"消息内容: {text[:100]}{'...' if len(text) > 100 else ''}")

        if not text:
            log_lines.append(f"✗ 请求失败: 消息内容为空")
            logger.info('\n'.join(log_lines))
            return jsonify({
                'code': 400,
                'message': '消息内容不能为空'
            }), 400

        # 1. 检查推送模式，判断是否允许推送给用户
        should_push_to_users = True
        push_mode_info = ""

        try:
            push_settings = get_push_settings()
            if push_settings['mode'] == 'roundrobin':
                # 轮询模式：快速检查token是否活跃（使用内存缓存）
                from database import is_token_active
                if not is_token_active(channel_token):
                    should_push_to_users = False
                    push_mode_info = f"[轮询模式-非活跃令牌] 已保存到数据库但未推送给用户"
                    log_lines.append(f"当前为轮询模式，令牌 {channel_token} 不在活跃列表")
                    log_lines.append(f"令牌快速检查: 非活跃")
        except Exception as e:
            logger.error(f"检查推送模式失败: {e}")
            # 出错时默认允许推送，避免消息丢失

        # 2. 保存消息到数据库（记录使用的token）
        message_id = save_message(channel_id, title, text, token=channel_token)
        log_lines.append(f"消息已保存到数据库, 频道ID: {channel_id}, 消息ID: {message_id}, Token: {channel_token}")

        # 2.5. 调用AI分析消息（根据配置使用doubao或siliconflow）
        # 检查是否包含图片或有效文本（保留图片用于AI分析）
        validated_content = filter_and_validate_content(text)
        if validated_content:
            # 获取当前时间戳用于日志
            current_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            # 传递原始text给AI分析（包含图片），不要传递过滤后的validated_content
            analyze_message(message_id, text, token=channel_token, timestamp=current_timestamp)
            provider_name = "SiliconFlow" if config.AI_PROVIDER == 'siliconflow' else "豆包"
            log_lines.append(f"已提交{provider_name}AI分析任务（后台执行）")
        else:
            log_lines.append(f"消息无有效内容，跳过AI分析")

        # 3. 根据推送模式决定是否转发到 Node.js 推送服务
        if not should_push_to_users:
            # 轮询模式下非活跃令牌：只保存数据库，不推送
            elapsed_time = (datetime.now() - start_time).total_seconds() * 1000
            log_lines.append(f"✓ 消息已保存 (耗时: {elapsed_time:.0f}ms)")
            log_lines.append(f"  {push_mode_info}")
            log_lines.append(f"{'='*60}")
            logger.info('\n'.join(log_lines))
            return jsonify({
                'code': 0,
                'message': push_mode_info
            }), 200

        # 转发到 Node.js 推送服务
        try:
            # 获取订阅该频道的用户及其未读数
            subscribers = get_subscribers_for_channel(channel_id)
            log_lines.append(f"订阅用户数: {len(subscribers)}")

            # 为每个订阅者计算未读数
            subscribers_with_unread = []
            for socket_id in subscribers:
                # 获取该用户订阅的所有频道
                subscriptions = get_user_subscriptions(socket_id)
                unread_counts = {}
                for sub_channel_id in subscriptions:
                    unread_counts[sub_channel_id] = get_unread_count(socket_id, sub_channel_id)

                subscribers_with_unread.append({
                    'socket_id': socket_id,
                    'unread_counts': unread_counts
                })

            log_lines.append(f"正在转发到推送服务: {PUSH_SERVICE_URL}/api/push")

            response = requests.post(
                f"{PUSH_SERVICE_URL}/api/push",
                json={
                    'channel_id': channel_id,
                    'title': title,
                    'content': text,
                    'subscribers': subscribers_with_unread  # 传入订阅者列表及未读数
                },
                timeout=5
            )

            result = response.json()
            log_lines.append(f"推送服务响应状态码: {response.status_code}")
            log_lines.append(f"推送服务响应内容: {result}")

            elapsed_time = (datetime.now() - start_time).total_seconds() * 1000

            if response.status_code == 200 and result.get('success'):
                log_lines.append(f"✓ 推送成功 (耗时: {elapsed_time:.0f}ms)")
                log_lines.append(f"{'='*60}")
                logger.info('\n'.join(log_lines))
                return jsonify({
                    'code': 0,
                    'message': 'success'
                }), 200
            else:
                log_lines.append(f"✗ 推送服务返回错误 (耗时: {elapsed_time:.0f}ms)")
                log_lines.append(f"{'='*60}")
                logger.warning('\n'.join(log_lines))
                return jsonify({
                    'code': 500,
                    'message': '推送服务异常'
                }), 500

        except requests.exceptions.Timeout:
            elapsed_time = (datetime.now() - start_time).total_seconds() * 1000
            log_lines.append(f"✗ 推送服务超时 (耗时: {elapsed_time:.0f}ms)")
            log_lines.append(f"{'='*60}")
            logger.error('\n'.join(log_lines))
            return jsonify({
                'code': 500,
                'message': '推送服务超时'
            }), 500

        except requests.exceptions.ConnectionError as e:
            elapsed_time = (datetime.now() - start_time).total_seconds() * 1000
            log_lines.append(f"✗ 推送服务连接失败: {str(e)} (耗时: {elapsed_time:.0f}ms)")
            log_lines.append(f"{'='*60}")
            logger.error('\n'.join(log_lines))
            return jsonify({
                'code': 500,
                'message': '推送服务不可用'
            }), 500

    except Exception as e:
        elapsed_time = (datetime.now() - start_time).total_seconds() * 1000
        log_lines.append(f"✗ 服务器处理异常: {str(e)} (耗时: {elapsed_time:.0f}ms)")
        import traceback
        log_lines.append(f"异常堆栈:\n{traceback.format_exc()}")
        log_lines.append(f"{'='*60}")
        logger.error('\n'.join(log_lines))
        return jsonify({
            'code': 500,
            'message': f'服务器处理异常: {str(e)}'
        }), 500

@app.route('/api/tokens', methods=['GET'])
def get_tokens_api():
    """获取所有 token 映射（管理用）"""
    tokens = get_all_tokens()
    return jsonify({
        'success': True,
        'tokens': tokens
    })

@app.route('/api/tokens/grouped', methods=['GET'])
def get_tokens_grouped_api():
    """获取按频道分组的 token 列表（管理用）"""
    from database import get_db_connection, get_tokens_last_message_time
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT channel_id, token, created_at
        FROM channel_tokens
        ORDER BY channel_id, created_at
    """)
    rows = cursor.fetchall()
    conn.close()

    # 获取所有token的最后消息时间
    tokens_last_message = get_tokens_last_message_time()

    # 按频道分组，并计算每个频道的最新令牌消息时间
    tokens_by_channel = {}
    channel_latest_token_time = {}  # 记录每个频道最新的令牌消息时间

    for row in rows:
        channel_id = row['channel_id']
        if channel_id not in tokens_by_channel:
            tokens_by_channel[channel_id] = []

        token_last_time = tokens_last_message.get(row['token'])
        tokens_by_channel[channel_id].append({
            'token': row['token'],
            'created_at': row['created_at'],
            'last_message_time': token_last_time
        })

        # 更新该频道的最新令牌消息时间
        if token_last_time:
            if channel_id not in channel_latest_token_time or token_last_time > channel_latest_token_time[channel_id]:
                channel_latest_token_time[channel_id] = token_last_time

    return jsonify({
        'success': True,
        'tokens_by_channel': tokens_by_channel,
        'channel_latest_token_time': channel_latest_token_time  # 返回每个频道的最新令牌消息时间
    })

@app.route('/api/tokens', methods=['POST'])
def add_token_api():
    """添加/删除 token（管理用）"""
    try:
        data = request.json

        # 处理删除操作 - 删除整个频道
        if data.get('action') == 'delete':
            channel_id = data.get('channel_id')
            if not channel_id:
                return jsonify({
                    'success': False,
                    'error': '缺少 channel_id'
                }), 400

            delete_channel(channel_id)
            return jsonify({
                'success': True,
                'message': '频道删除成功'
            })

        # 处理删除单个token操作
        if data.get('action') == 'delete_token':
            channel_id = data.get('channel_id')
            token = data.get('token')
            if not channel_id or not token:
                return jsonify({
                    'success': False,
                    'error': '缺少 channel_id 或 token'
                }), 400

            from database import get_db_connection
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM channel_tokens WHERE channel_id = ? AND token = ?",
                         (channel_id, token))
            conn.commit()
            conn.close()

            return jsonify({
                'success': True,
                'message': 'Token 删除成功'
            })

        # 处理只更新频道信息（不处理令牌）
        if data.get('action') == 'update_channel':
            channel_id = data.get('channel_id')
            channel_name = data.get('name', '')
            channel_type = data.get('type', 'public')
            channel_category = data.get('category', '')
            channel_avatar = data.get('avatar')

            if not channel_name:
                return jsonify({
                    'success': False,
                    'error': '缺少频道名称'
                }), 400

            # 如果没有提供 channel_id，自动生成下一个数字ID
            if not channel_id:
                channel_id = get_next_channel_id()

            # 处理头像上传
            avatar_url = None
            avatar_update = False
            avatar_base64 = None
            if channel_avatar is not None:
                avatar_update = True
                if channel_avatar and channel_avatar.startswith('data:image'):
                    avatar_base64 = channel_avatar
                    uploaded_url = upload_to_image_host(channel_avatar)
                    avatar_url = uploaded_url if uploaded_url else channel_avatar
                else:
                    avatar_url = channel_avatar or None

            # 检查频道是否存在，不存在则创建
            from database import get_db_connection
            conn = get_db_connection()
            cursor = conn.cursor()

            # 检查频道是否存在
            cursor.execute("SELECT id FROM channels WHERE id = ?", (channel_id,))
            channel_exists = cursor.fetchone() is not None

            if not channel_exists:
                # 创建新频道
                create_channel(channel_id, channel_name, channel_type, channel_category, avatar_url)
            else:
                # 更新现有频道
                if avatar_update:
                    cursor.execute("""
                        UPDATE channels
                        SET name = ?, type = ?, category_id = ?, avatar = ?
                        WHERE id = ?
                    """, (channel_name, channel_type, channel_category, avatar_url, channel_id))

                    if avatar_base64:
                        save_avatar_backup(channel_id, avatar_base64)
                        logger.info(f"已保存频道 {channel_id} 的头像备份")
                    elif avatar_url is None:
                        try:
                            import os
                            backup_path = os.path.join(AVATAR_BACKUP_DIR, f"{channel_id}.png")
                            if os.path.exists(backup_path):
                                os.remove(backup_path)
                                logger.info(f"已删除频道 {channel_id} 的头像备份")
                        except Exception as e:
                            logger.error(f"删除头像备份失败: {e}")
                else:
                    cursor.execute("""
                        UPDATE channels
                        SET name = ?, type = ?, category_id = ?
                        WHERE id = ?
                    """, (channel_name, channel_type, channel_category, channel_id))

            conn.commit()
            conn.close()

            return jsonify({
                'success': True,
                'message': '频道保存成功',
                'channel_id': channel_id
            })

        # 添加新 token（action 不是 delete、delete_token 或 update_channel）
        token = data.get('token') or ''  # 处理 null 和空字符串
        if token:
            token = token.strip()

        channel_id = data.get('channel_id')
        channel_name = data.get('name', '')
        channel_type = data.get('type')  # 不再使用默认值，从数据库读取
        channel_category = data.get('category')  # 标签（如：domestic, foreign）
        # 使用 get() 的默认值为 None，这样可以区分"没有 avatar 字段"和"avatar 为空字符串"
        channel_avatar = data.get('avatar')  # 头像base64数据或URL，None表示未修改，空字符串表示清空

        # 如果是添加令牌操作，且没有指定 type 和 category，从数据库读取现有值
        if data.get('action') == 'add' and (channel_type is None or channel_category is None):
            existing_channel = get_channel(channel_id)
            if existing_channel:
                if channel_type is None:
                    channel_type = existing_channel.get('type')
                if channel_category is None:
                    channel_category = existing_channel.get('category')
            else:
                # 频道不存在，使用默认值
                if channel_type is None:
                    channel_type = 'public'
                if channel_category is None:
                    channel_category = ''

        if not channel_name:
            return jsonify({
                'success': False,
                'error': '缺少频道名称'
            }), 400

        # 如果没有提供 channel_id，自动生成下一个数字ID
        if not channel_id:
            channel_id = get_next_channel_id()

        # 处理头像上传
        avatar_url = None
        avatar_update = False  # 标记是否需要更新头像字段
        avatar_base64 = None  # 保存原始的 base64 数据用于备份
        if channel_avatar is not None:  # 注意：明确判断是否为 None
            avatar_update = True  # 只要发送了 avatar 字段，就需要更新
            # 如果是base64数据（以data:image开头）
            if channel_avatar and channel_avatar.startswith('data:image'):
                # 保存 base64 数据用于稍后备份
                avatar_base64 = channel_avatar

                # 上传到图床
                uploaded_url = upload_to_image_host(channel_avatar)

                # 如果图床上传成功，使用图床URL；否则使用base64数据
                if uploaded_url:
                    avatar_url = uploaded_url
                else:
                    avatar_url = channel_avatar
            # 否则直接作为URL使用（可能是图床URL或空字符串）
            else:
                avatar_url = channel_avatar or None

        # 检查频道是否存在,不存在则创建
        if not get_channel(channel_id):
            # 自动创建频道，包含类型、标签和头像
            create_channel(channel_id, channel_name, channel_type, channel_category, avatar_url)

        # 如果 token 为空,自动生成16位
        if not token:
            import secrets
            token = secrets.token_hex(8)  # 16个字符(0-9,a-f)

        # 检查 token 唯一性
        existing_channel = get_channel_by_token(token)

        if existing_channel:
            if existing_channel != channel_id:
                # token被其他频道使用
                return jsonify({
                    'success': False,
                    'error': f'Token 已被频道 {existing_channel} 使用,请更换'
                }), 400
            else:
                # token已经在当前频道存在
                return jsonify({
                    'success': False,
                    'error': 'Token 已存在于当前频道'
                }), 400

        # Token不存在，添加新token到频道（追加模式）
        from database import get_db_connection
        conn = get_db_connection()
        cursor = conn.cursor()

        # 添加新token
        cursor.execute("INSERT INTO channel_tokens (channel_id, token) VALUES (?, ?)",
                     (channel_id, token))

        # 更新频道信息
        if avatar_update:
            cursor.execute("""
                UPDATE channels
                SET name = ?, type = ?, category_id = ?, avatar = ?
                WHERE id = ?
            """, (channel_name, channel_type, channel_category, avatar_url, channel_id))

            # 处理头像备份
            if avatar_base64:
                save_avatar_backup(channel_id, avatar_base64)
                logger.info(f"已保存频道 {channel_id} 的头像备份")
            elif avatar_url is None:
                try:
                    import os
                    backup_path = os.path.join(AVATAR_BACKUP_DIR, f"{channel_id}.png")
                    if os.path.exists(backup_path):
                        os.remove(backup_path)
                        logger.info(f"已删除频道 {channel_id} 的头像备份")
                except Exception as e:
                    logger.error(f"删除头像备份失败: {e}")
        else:
            # 没有修改头像，只更新基本信息
            cursor.execute("""
                UPDATE channels
                SET name = ?, type = ?, category_id = ?
                WHERE id = ?
            """, (channel_name, channel_type, channel_category, channel_id))

        conn.commit()
        conn.close()

        return jsonify({
            'success': True,
            'message': 'Token 添加成功',
            'channel_id': channel_id,
            'token': token
        })

    except Exception as e:
        logger.error(f"添加token异常: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
@app.route('/api/channels')
def get_channels_api():
    """获取频道列表（管理员看全部，普通用户根据订阅权限过滤，支持分页）"""
    try:
        # 获取请求参数
        socket_id = request.args.get('socket_id')
        is_admin = request.args.get('admin') == 'true'
        page = request.args.get('page', 1, type=int)  # 页码，默认1
        size = request.args.get('size', 20, type=int)  # 每页数量，默认20
        order_by = request.args.get('order_by', 'latest_message')  # 排序方式，默认按最新消息

        all_channels = get_all_channels(order_by=order_by)

        # 管理员可以看到所有频道（不分页）
        if is_admin:
            return jsonify({
                'channels': all_channels,
                'is_admin': True
            })

        # 如果没有提供 socket_id，只返回公开频道
        if not socket_id:
            channels = [ch for ch in all_channels if ch.get('type') == 'public']
            total = len(channels)
            start = (page - 1) * size
            end = start + size
            paginated_channels = channels[start:end]

            return jsonify({
                'channels': paginated_channels,
                'all_public': True,
                'pagination': {
                    'page': page,
                    'size': size,
                    'total': total,
                    'has_more': end < total
                }
            })

        # 获取用户已订阅的频道
        try:
            subscribed_channel_ids = get_user_subscriptions(socket_id)
            subscribed_channel_ids_set = set(subscribed_channel_ids) if subscribed_channel_ids else set()
        except Exception as e:
            logger.error(f"获取用户订阅失败: {e}")
            subscribed_channel_ids_set = set()

        # 过滤频道：
        # 1. 公开频道：所有人可见
        # 2. 私人频道：仅订阅用户可见
        channels = []
        for ch in all_channels:
            if ch.get('type') == 'public':
                # 公开频道，所有人都可见
                channels.append(ch)
            elif ch.get('type') == 'private' and ch.get('id') in subscribed_channel_ids_set:
                # 私人频道，且用户已订阅
                channels.append(ch)

        # 分页返回
        total = len(channels)
        start = (page - 1) * size
        end = start + size
        paginated_channels = channels[start:end]

        return jsonify({
            'channels': paginated_channels,
            'pagination': {
                'page': page,
                'size': size,
                'total': total,
                'has_more': end < total
            }
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/channels/<channel_id>')
def get_single_channel_api(channel_id):
    """获取单个频道信息（用于动态加载）"""
    try:
        socket_id = request.args.get('socket_id')

        channel = get_channel(channel_id)
        if not channel:
            return jsonify({'success': False, 'error': '频道不存在'}), 404

        # 如果是私人频道，检查用户权限
        if channel.get('type') == 'private' and socket_id:
            subscribed_channel_ids = get_user_subscriptions(socket_id)
            subscribed_channel_ids_set = set(subscribed_channel_ids) if subscribed_channel_ids else set()

            if channel_id not in subscribed_channel_ids_set:
                return jsonify({'success': False, 'error': '无权访问'}), 403

        return jsonify({
            'success': True,
            'channel': channel
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/channels/latest-time')
def get_channels_latest_time_api():
    """批量获取频道最新消息时间

    Query Parameters:
        channel_ids: 频道ID列表，逗号分隔（可选，不传则查询所有频道）

    Returns:
        {
            "success": true,
            "latest_times": {
                "1": "2026-04-19 12:00:00",
                "2": "2026-04-19 11:00:00"
            }
        }
    """
    try:
        # 获取频道ID列表参数
        channel_ids_str = request.args.get('channel_ids', '')
        if channel_ids_str:
            channel_ids = [cid.strip() for cid in channel_ids_str.split(',') if cid.strip()]
            latest_times = get_channels_latest_message_time(channel_ids)
        else:
            latest_times = get_channels_latest_message_time()

        return jsonify({
            'success': True,
            'latest_times': latest_times
        })
    except Exception as e:
        logger.error(f"获取频道最新消息时间失败: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/health')
def health():
    """健康检查"""
    try:
        # 从数据库获取统计
        stats = get_stats()

        # 尝试获取 Node.js 推送服务状态
        try:
            response = requests.get(f"{PUSH_SERVICE_URL}/health", timeout=3)
            push_service_status = response.json()
        except:
            push_service_status = {'status': 'unavailable'}

        # 设置 CORS 头
        result = jsonify({
            'status': 'ok',
            'flask': 'running',
            'push_service': push_service_status,
            'total_messages': stats['total_messages'],
            'active_channels': stats['channel_count'],
            'online_users': push_service_status.get('online_users', 0)
        })
        result.headers.add('Access-Control-Allow-Origin', '*')
        return result
    except Exception as e:
        result = jsonify({
            'status': 'degraded',
            'flask': 'running',
            'push_service': 'unavailable',
            'total_messages': 0,
            'active_channels': 0,
            'online_users': 0,
            'error': str(e)
        })
        result.headers.add('Access-Control-Allow-Origin', '*')
        return result, 503

# ============ 系统维护 API ============

@app.route('/api/admin/cleanup-sessions', methods=['POST'])
@require_admin
def cleanup_sessions_api():
    """清理过期会话（需要管理员权限）"""
    try:
        data = request.json or {}
        days = data.get('days', 7)  # 默认清理7天前的

        if not isinstance(days, int) or days < 1:
            return jsonify({'error': '天数必须是正整数'}), 400

        deleted_count = cleanup_old_sessions(days)

        logger.info(f"清理了 {deleted_count} 个过期会话（{days}天前）")

        return jsonify({
            'success': True,
            'deleted_count': deleted_count,
            'days': days,
            'message': f'成功清理 {deleted_count} 个过期会话'
        })
    except Exception as e:
        logger.error(f"清理会话失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/stats/sessions', methods=['GET'])
@require_admin
def session_stats_api():
    """获取会话统计信息（需要管理员权限）"""
    try:
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # 总会话数
        cursor.execute("SELECT COUNT(*) as count FROM user_sessions")
        total_sessions = cursor.fetchone()['count']

        # 各日期会话数
        cursor.execute("""
            SELECT DATE(created_at) as date, COUNT(*) as count
            FROM user_sessions
            GROUP BY DATE(created_at)
            ORDER BY date DESC
            LIMIT 7
        """)
        daily_stats = [dict(row) for row in cursor.fetchall()]

        # 会话状态分布
        cursor.execute("""
            SELECT
                COUNT(CASE WHEN current_channel IS NULL THEN 1 END) as no_channel,
                COUNT(CASE WHEN current_channel IS NOT NULL THEN 1 END) as with_channel
            FROM user_sessions
        """)
        channel_stats = cursor.fetchone()

        conn.close()

        return jsonify({
            'total_sessions': total_sessions,
            'daily_stats': daily_stats,
            'channel_stats': {
                'no_channel': channel_stats['no_channel'],
                'with_channel': channel_stats['with_channel']
            }
        })
    except Exception as e:
        logger.error(f"获取会话统计失败: {e}")
        return jsonify({'error': str(e)}), 500

# ============ WebSocket 会话管理 API ============

@app.route('/api/ws/connect', methods=['POST'])
def ws_connect():
    """WebSocket 连接时调用"""
    try:
        data = request.json
        socket_id = data.get('socket_id')
        user_id = data.get('user_id')  # 获取用户ID

        if not socket_id:
            return jsonify({'error': '缺少 socket_id'}), 400

        create_session(socket_id, user_id)
        return jsonify({'success': True, 'message': '会话已创建'})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/ws/disconnect', methods=['POST'])
def ws_disconnect():
    """WebSocket 断开时调用"""
    try:
        data = request.json
        socket_id = data.get('socket_id')

        if not socket_id:
            return jsonify({'error': '缺少 socket_id'}), 400

        delete_session(socket_id)
        return jsonify({'success': True, 'message': '会话已删除'})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/ws/subscribe', methods=['POST'])
def ws_subscribe():
    """订阅频道"""
    try:
        data = request.json
        socket_id = data.get('socket_id')
        channel_ids = data.get('channel_ids', [])

        if not socket_id or not channel_ids:
            return jsonify({'error': '缺少必要参数'}), 400

        subscribe_channels(socket_id, channel_ids)
        return jsonify({'success': True, 'message': '订阅成功'})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/ws/channels-summary', methods=['POST'])
def ws_channels_summary():
    """批量获取频道的最新消息摘要和未读数（飞书/钉钉设计，支持分页）"""
    try:
        data = request.json
        socket_id = data.get('socket_id')
        page = data.get('page', 1)  # 页码，默认1
        size = data.get('size', 20)  # 每页数量，默认20
        channel_ids = data.get('channel_ids', [])  # 指定频道ID列表

        if not socket_id:
            return jsonify({'error': '缺少必要参数'}), 400

        # 如果指定了channel_ids，直接返回这些频道的摘要
        if channel_ids:
            # 保持字符串类型，不转换，因为数据库channel_id是TEXT类型
            latest_messages_map = get_channels_latest_messages_batch(channel_ids)

            channels_summary = []
            for channel_id in channel_ids:
                channel = get_channel(channel_id)
                if not channel:
                    continue

                # 检查权限
                if channel.get('type') == 'private':
                    subscribed_channel_ids = get_user_subscriptions(socket_id)
                    if channel_id not in (subscribed_channel_ids or []):
                        continue

                channel_info = {
                    'id': channel_id,
                    'name': channel.get('name'),
                    'type': channel.get('type'),
                    'category_id': channel.get('category_id')
                }

                if channel_id in latest_messages_map:
                    channel_info['latest_message'] = latest_messages_map[channel_id]

                channels_summary.append(channel_info)

            # 获取这些频道的未读数
            unread_counts = get_all_unread_counts(socket_id)
            filtered_unread_counts = {
                str(cid): unread_counts.get(str(cid), 0)
                for cid in channel_ids
            }

            return jsonify({
                'success': True,
                'channels': channels_summary,
                'unread_counts': filtered_unread_counts
            })

        # 获取用户可见的所有频道（分页模式）
        all_channels = get_all_channels(order_by='latest_message')

        # 如果是普通用户，过滤私人频道
        subscribed_channel_ids = get_user_subscriptions(socket_id)
        subscribed_channel_ids_set = set(subscribed_channel_ids) if subscribed_channel_ids else set()

        # 过滤频道：公开频道全部可见，私人频道只显示已订阅的
        visible_channels = []
        for ch in all_channels:
            if ch.get('type') == 'public' or ch.get('id') in subscribed_channel_ids_set:
                visible_channels.append(ch)

        # 分页处理
        total = len(visible_channels)
        start = (page - 1) * size
        end = start + size
        paginated_channels = visible_channels[start:end]

        # 批量获取当前页频道的最新消息
        channel_ids = [ch.get('id') for ch in paginated_channels]
        latest_messages_map = get_channels_latest_messages_batch(channel_ids)

        # 构建返回数据
        channels_summary = []
        for channel in paginated_channels:
            channel_id = channel.get('id')
            channel_info = {
                'id': channel_id,
                'name': channel.get('name'),
                'type': channel.get('type'),
                'category_id': channel.get('category_id')
            }

            # 从批量查询结果中获取最新消息
            if channel_id in latest_messages_map:
                channel_info['latest_message'] = latest_messages_map[channel_id]

            channels_summary.append(channel_info)

        # 批量获取所有未读数（不分页，获取全部频道的未读数）
        unread_counts = get_all_unread_counts(socket_id)

        return jsonify({
            'success': True,
            'channels': channels_summary,
            'unread_counts': unread_counts,
            'pagination': {
                'page': page,
                'size': size,
                'total': total,
                'has_more': end < total
            }
        })

    except Exception as e:
        logger.error(f"获取频道摘要失败: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/ws/switch-channel', methods=['POST'])
def ws_switch_channel():
    """切换当前频道（带订阅权限验证）"""
    try:
        data = request.json
        socket_id = data.get('socket_id')
        channel_id = data.get('channel_id')
        limit = data.get('limit', 40)  # 默认40条
        offset = data.get('offset', 0)  # 默认从0开始
        last_loaded_timestamp = data.get('last_loaded_timestamp')  # 上一次加载的第一条消息时间戳

        if not socket_id or not channel_id:
            return jsonify({'error': '缺少必要参数'}), 400

        # 验证用户是否有权限访问该频道
        channel = get_channel(channel_id)
        if not channel:
            return jsonify({'error': '频道不存在'}), 404

        # admin 用户拥有所有频道访问权限
        if socket_id == 'admin':
            pass  # 跳过权限检查
        # 如果是私人频道，检查用户是否已订阅
        elif channel.get('type') == 'private':
            subscribed_channel_ids = get_user_subscriptions(socket_id)
            subscribed_channel_ids_set = set(subscribed_channel_ids) if subscribed_channel_ids else set()

            if str(channel_id) not in subscribed_channel_ids_set:
                logger.warning(f"用户 {socket_id} 尝试访问未订阅的私人频道 {channel_id}")
                return jsonify({'error': '您没有权限访问此频道'}), 403

        set_current_channel(socket_id, channel_id)

        # 重置未读数（标记为已读）
        mark_messages_as_read(socket_id, channel_id)

        # 获取历史消息（支持分页，传入last_loaded_timestamp用于判断日期分割线）
        result = get_channel_messages(channel_id, limit=limit, offset=offset, last_loaded_timestamp=last_loaded_timestamp)

        # 获取用户所有频道的未读数（批量查询，性能优化）
        unread_counts = get_all_unread_counts(socket_id)

        return jsonify({
            'success': True,
            'unread_counts': unread_counts,
            'history': result['messages'],
            'pagination': {
                'total': result['total'],
                'loaded': result['loaded'],
                'has_more': result['loaded'] < result['total']
            }
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/ws/mark-read', methods=['POST'])
def mark_read():
    """标记频道消息为已读"""
    try:
        data = request.json
        socket_id = data.get('socket_id')
        channel_id = data.get('channel_id')

        if not socket_id or not channel_id:
            return jsonify({'error': '缺少必要参数'}), 400

        # 清除未读数
        mark_messages_as_read(socket_id, channel_id)

        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/channel/doubao-summary', methods=['GET'])
def get_channel_doubao_summary_api():
    """获取频道豆包AI分析汇总（分页）"""
    try:
        channel_id = request.args.get('channel_id')
        offset = request.args.get('offset', 0, type=int)
        limit = request.args.get('limit', 10, type=int)

        if not channel_id:
            return jsonify({'error': '缺少频道ID'}), 400

        # 获取豆包分析汇总
        summary = get_channel_doubao_summary(channel_id, offset=offset, limit=limit)

        return jsonify({
            'success': True,
            'summary': summary
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/messages/<int:message_id>', methods=['GET'])
def get_message_api(message_id):
    """获取单条消息的完整内容"""
    try:
        message = get_message_by_id(message_id)

        if not message:
            return jsonify({'success': False, 'error': '消息不存在'}), 404

        return jsonify({
            'success': True,
            'message': message
        })
    except Exception as e:
        logger.error(f"获取消息失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ============ 股票管理 API ============

@app.route('/api/admin/stocks/search', methods=['GET'])
def search_stocks_api():
    """股票联想搜索"""
    try:
        query = request.args.get('q', '').strip()

        if not query:
            return jsonify({'success': True, 'stocks': []})

        conn = get_db_connection()
        cursor = conn.cursor()

        # 多条件模糊查询
        search_pattern = f'%{query}%'
        cursor.execute("""
            SELECT code, name, pinyin_abbr
            FROM stocks
            WHERE status = 1
              AND (
                code LIKE ?
                OR name LIKE ?
                OR pinyin LIKE ?
                OR pinyin_abbr LIKE ?
              )
            ORDER BY
                CASE WHEN code = ? THEN 1
                     WHEN name = ? THEN 2
                     ELSE 3
                END
            LIMIT 10
        """, (search_pattern, search_pattern, search_pattern, search_pattern, query, query))

        results = cursor.fetchall()
        conn.close()

        stocks = [
            {'code': r[0], 'name': r[1], 'pinyin_abbr': r[2]}
            for r in results
        ]

        return jsonify({'success': True, 'stocks': stocks})
    except Exception as e:
        logger.error(f"搜索股票失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/admin/stocks/sync-logs', methods=['GET'])
def get_stock_sync_logs_api():
    """获取股票同步日志"""
    try:
        page = request.args.get('page', 1, type=int)
        size = request.args.get('size', 20, type=int)

        conn = get_db_connection()
        cursor = conn.cursor()

        # 获取总数
        cursor.execute("SELECT COUNT(*) FROM stock_sync_logs")
        total = cursor.fetchone()[0]

        # 分页查询
        offset = (page - 1) * size
        cursor.execute("""
            SELECT id, sync_time, total_count, new_count, update_count,
                   error_count, status, error_message, duration_seconds
            FROM stock_sync_logs
            ORDER BY sync_time DESC
            LIMIT ? OFFSET ?
        """, (size, offset))

        rows = cursor.fetchall()
        conn.close()

        logs = [
            {
                'id': r[0],
                'sync_time': r[1],
                'total_count': r[2],
                'new_count': r[3],
                'update_count': r[4],
                'error_count': r[5],
                'status': r[6],
                'error_message': r[7],
                'duration_seconds': r[8]
            }
            for r in rows
        ]

        return jsonify({
            'success': True,
            'logs': logs,
            'pagination': {
                'page': page,
                'size': size,
                'total': total,
                'has_more': offset + size < total
            }
        })
    except Exception as e:
        logger.error(f"获取同步日志失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/admin/stocks/sync-status', methods=['GET'])
def get_stock_sync_status_api():
    """获取股票同步状态"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # 获取最新一次同步
        cursor.execute("""
            SELECT sync_time, total_count, new_count, update_count,
                   error_count, status, duration_seconds
            FROM stock_sync_logs
            ORDER BY sync_time DESC
            LIMIT 1
        """)

        row = cursor.fetchone()
        conn.close()

        if row:
            return jsonify({
                'success': True,
                'last_sync': {
                    'sync_time': row[0],
                    'total_count': row[1],
                    'new_count': row[2],
                    'update_count': row[3],
                    'error_count': row[4],
                    'status': row[5],
                    'duration_seconds': row[6]
                }
            })
        else:
            return jsonify({
                'success': True,
                'last_sync': None
            })
    except Exception as e:
        logger.error(f"获取同步状态失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/admin/stocks/sync', methods=['POST'])
def trigger_stock_sync_api():
    """手动触发股票同步"""
    try:
        from stock_sync import sync_stock_data

        logger.info("=" * 70)
        logger.info("手动触发股票同步...")
        logger.info("=" * 70)

        # 在后台线程中执行同步（避免阻塞请求）
        def sync_in_background():
            try:
                logger.info("后台同步线程开始执行...")
                result = sync_stock_data()
                logger.info("=" * 70)
                logger.info(f"后台同步完成: {result}")
                logger.info("=" * 70)
            except Exception as e:
                logger.error("=" * 70)
                logger.error(f"后台同步失败: {e}")
                logger.error("=" * 70)
                import traceback
                logger.error(traceback.format_exc())

        import threading
        thread = threading.Thread(target=sync_in_background, daemon=True)
        thread.start()

        return jsonify({
            'success': True,
            'message': '股票同步任务已启动，正在后台执行...'
        })
    except Exception as e:
        logger.error(f"触发同步失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)}), 500

# ============ AI消息核对 API ============

@app.route('/api/admin/review/pending', methods=['GET'])
@require_admin
def get_pending_messages_api():
    """
    获取待核对消息列表
    参数:
        channel_ids: 频道ID列表（逗号分隔，如 "18,31"）
        start_date: 开始日期（如 "2026-04-01"）
        end_date: 结束日期（如 "2026-04-30"）
        page: 页码（默认1）
        size: 每页数量（默认20）
    """
    try:
        channel_ids_str = request.args.get('channel_ids', '')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        page = int(request.args.get('page', 1))
        size = int(request.args.get('size', 20))

        conn = get_db_connection()
        cursor = conn.cursor()

        # 构建查询条件
        where_conditions = ["doubao_ai IS NOT NULL"]
        params = []

        # 频道筛选
        if channel_ids_str:
            channel_ids = [cid.strip() for cid in channel_ids_str.split(',') if cid.strip()]
            if channel_ids:
                placeholders = ','.join(['?' for _ in channel_ids])
                where_conditions.append(f"channel_id IN ({placeholders})")
                params.extend(channel_ids)

        # 日期筛选
        if start_date:
            where_conditions.append("DATE(created_at) >= ?")
            params.append(start_date)

        if end_date:
            where_conditions.append("DATE(created_at) <= ?")
            params.append(end_date)

        where_clause = " AND ".join(where_conditions)

        # 查询总数
        count_sql = f"SELECT COUNT(*) FROM messages WHERE {where_clause}"
        cursor.execute(count_sql, params)
        total = cursor.fetchone()[0]

        # 分页查询
        offset = (page - 1) * size
        list_sql = f"""
            SELECT id, channel_id, content, doubao_ai, created_at
            FROM messages
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """
        cursor.execute(list_sql, params + [size, offset])
        rows = cursor.fetchall()

        messages = []
        for row in rows:
            messages.append({
                'id': row[0],
                'channel_id': row[1],
                'content': row[2],
                'doubao_ai': row[3],
                'created_at': row[4]
            })

        conn.close()

        return jsonify({
            'success': True,
            'messages': messages,
            'pagination': {
                'page': page,
                'size': size,
                'total': total,
                'has_more': offset + len(messages) < total
            }
        })

    except Exception as e:
        logger.error(f"获取待核对消息列表失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/admin/review/message/<int:message_id>', methods=['GET'])
@require_admin
def get_review_message_api(message_id):
    """获取单条消息详情（用于核对）"""
    try:
        msg = get_message_by_id(message_id)

        if not msg:
            return jsonify({'success': False, 'error': '消息不存在'}), 404

        # 解析AI分析结果
        ai_result = None
        if msg.get('doubao_ai'):
            try:
                ai_result = json.loads(msg['doubao_ai'])
            except:
                pass

        return jsonify({
            'success': True,
            'message': {
                'id': msg['id'],
                'channel_id': msg['channel_id'],
                'content': msg['content'],
                'doubao_ai': ai_result,
                'created_at': msg['created_at']
            }
        })

    except Exception as e:
        logger.error(f"获取消息详情失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/admin/review/correct', methods=['POST'])
@require_admin
def correct_ai_result_api():
    """
    提交修正结果，直接更新 messages.doubao_ai 字段
    Body:
        {
            "message_id": 123,
            "stocks": [
                {"stock_name": "三一重工", "stock_code": "600031", "operate": "买入"}
            ],
            "reviewed_by": "admin"
        }
    """
    try:
        data = request.json
        message_id = data.get('message_id')
        stocks = data.get('stocks', [])
        reviewed_by = data.get('reviewed_by', 'admin')

        if not message_id:
            return jsonify({'success': False, 'error': '缺少message_id'}), 400

        # 构建新的AI结果
        new_doubao_result = json.dumps({"stock_list": stocks}, ensure_ascii=False)

        # 更新数据库
        update_message_doubao(message_id, new_doubao_result)

        logger.info(f"消息 {message_id} AI结果已修正 by {reviewed_by}")

        return jsonify({
            'success': True,
            'message': '修正成功'
        })

    except Exception as e:
        logger.error(f"提交修正失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/admin/review/statistics', methods=['GET'])
@require_admin
def get_review_statistics_api():
    """
    获取核对统计信息
    参数:
        channel_ids: 频道ID列表（逗号分隔）
        start_date: 开始日期
        end_date: 结束日期
    """
    try:
        channel_ids_str = request.args.get('channel_ids', '')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')

        conn = get_db_connection()
        cursor = conn.cursor()

        # 构建查询条件
        where_conditions = ["doubao_ai IS NOT NULL"]
        params = []

        if channel_ids_str:
            channel_ids = [cid.strip() for cid in channel_ids_str.split(',') if cid.strip()]
            if channel_ids:
                placeholders = ','.join(['?' for _ in channel_ids])
                where_conditions.append(f"channel_id IN ({placeholders})")
                params.extend(channel_ids)

        if start_date:
            where_conditions.append("DATE(created_at) >= ?")
            params.append(start_date)

        if end_date:
            where_conditions.append("DATE(created_at) <= ?")
            params.append(end_date)

        where_clause = " AND ".join(where_conditions)

        # 统计总数
        count_sql = f"SELECT COUNT(*) FROM messages WHERE {where_clause}"
        cursor.execute(count_sql, params)
        total = cursor.fetchone()[0]

        conn.close()

        return jsonify({
            'success': True,
            'statistics': {
                'total_messages_with_ai': total
            }
        })

    except Exception as e:
        logger.error(f"获取统计信息失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ============ 豆包AI配置管理 API ============

@app.route('/api/admin/doubao-config', methods=['GET'])
def get_doubao_config():
    """获取豆包AI配置（需要管理员权限）"""
    try:
        # 验证管理员token
        admin_token = request.args.get('admin_token') or request.headers.get('X-Admin-Token')
        if not admin_token or admin_token != ADMIN_TOKEN:
            return jsonify({'success': False, 'message': '无权访问'}), 403

        return jsonify({
            'success': True,
            'config': {
                'api_key': config.DOUBAO_API_KEY,
                'api_url': config.DOUBAO_API_URL,
                'model': config.DOUBAO_MODEL,
                'prompt': config.DOUBAO_PROMPT
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/admin/doubao-config', methods=['POST'])
def update_doubao_config():
    """更新豆包AI配置（需要管理员权限）"""
    try:
        # 验证管理员token
        data = request.json
        admin_token = data.get('admin_token')
        if not admin_token or admin_token != ADMIN_TOKEN:
            return jsonify({'success': False, 'message': '无权访问'}), 403

        # 获取参数
        api_key = data.get('api_key')
        api_url = data.get('api_url')
        model = data.get('model')
        prompt = data.get('prompt')

        # 更新配置（内存+文件）
        success = config.update_doubao_config(
            api_key=api_key,
            api_url=api_url,
            model=model,
            prompt=prompt
        )

        if success:
            logger.info("豆包AI配置已更新")
            return jsonify({
                'success': True,
                'message': '配置更新成功'
            })
        else:
            return jsonify({
                'success': False,
                'message': '配置写入失败'
            }), 500
    except Exception as e:
        logger.error(f"更新豆包配置失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/admin/siliconflow-config', methods=['GET'])
def get_siliconflow_config():
    """获取硅基流动AI配置（需要管理员权限）"""
    try:
        # 验证管理员token
        admin_token = request.args.get('admin_token') or request.headers.get('X-Admin-Token')
        if not admin_token or admin_token != ADMIN_TOKEN:
            return jsonify({'success': False, 'message': '无权访问'}), 403

        return jsonify({
            'success': True,
            'config': {
                'api_key': config.SILICONFLOW_API_KEY,
                'api_url': config.SILICONFLOW_API_URL,
                'model': config.SILICONFLOW_MODEL,
                'prompt': config.SILICONFLOW_PROMPT
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/admin/siliconflow-config', methods=['POST'])
def update_siliconflow_config():
    """更新硅基流动AI配置（需要管理员权限）"""
    try:
        # 验证管理员token
        data = request.json
        admin_token = data.get('admin_token')
        if not admin_token or admin_token != ADMIN_TOKEN:
            return jsonify({'success': False, 'message': '无权访问'}), 403

        # 获取参数
        api_key = data.get('api_key')
        api_url = data.get('api_url')
        model = data.get('model')
        prompt = data.get('prompt')

        # 更新配置（内存+文件）
        success = config.update_siliconflow_config(
            api_key=api_key,
            api_url=api_url,
            model=model,
            prompt=prompt
        )

        if success:
            logger.info("硅基流动AI配置已更新")
            return jsonify({
                'success': True,
                'message': '配置更新成功'
            })
        else:
            return jsonify({
                'success': False,
                'message': '配置写入失败'
            }), 500
    except Exception as e:
        logger.error(f"更新硅基流动配置失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/admin/ai-provider', methods=['GET'])
def get_ai_provider():
    """获取当前使用的AI提供商（需要管理员权限）"""
    try:
        # 验证管理员token
        admin_token = request.args.get('admin_token') or request.headers.get('X-Admin-Token')
        if not admin_token or admin_token != ADMIN_TOKEN:
            return jsonify({'success': False, 'message': '无权访问'}), 403

        return jsonify({
            'success': True,
            'provider': config.AI_PROVIDER
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/admin/ai-provider', methods=['POST'])
def update_ai_provider():
    """更新当前使用的AI提供商（需要管理员权限）"""
    try:
        # 验证管理员token
        data = request.json
        admin_token = data.get('admin_token')
        if not admin_token or admin_token != ADMIN_TOKEN:
            return jsonify({'success': False, 'message': '无权访问'}), 403

        # 获取provider
        provider = data.get('provider')
        if not provider:
            return jsonify({'success': False, 'message': '缺少provider参数'}), 400

        # 更新配置（内存+文件）
        success = config.update_ai_provider(provider)

        if success:
            logger.info(f"AI提供商已切换到: {provider}")
            return jsonify({
                'success': True,
                'message': f'已切换到{provider}',
                'provider': provider
            })
        else:
            return jsonify({
                'success': False,
                'message': '配置写入失败'
            }), 500
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        logger.error(f"更新AI提供商失败: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

# ============ 认证相关 API ============

# 验证码缓存（开发环境使用，生产环境应该用 Redis）
captcha_cache = {}

@app.route('/api/auth/captcha', methods=['GET'])
def get_captcha():
    """生成图形验证码"""
    try:
        from PIL import Image, ImageDraw, ImageFont
        import io

        # 生成随机4位数字
        captcha_text = ''.join(random.choices(string.digits, k=4))

        # 直接创建大图片
        width, height = 200, 80
        image = Image.new('RGB', (width, height), color=(255, 255, 255))
        draw = ImageDraw.Draw(image)

        # 尝试加载大字体
        try:
            # 尝试使用系统字体
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 48)
        except:
            try:
                font = ImageFont.truetype("arial.ttf", 48)
            except:
                # 如果都没有，使用默认字体并多次绘制来加粗
                font = ImageFont.load_default()

        # 添加一些干扰线
        for _ in range(5):
            x1 = random.randint(0, width)
            y1 = random.randint(0, height)
            x2 = random.randint(0, width)
            y2 = random.randint(0, height)
            draw.line([(x1, y1), (x2, y2)], fill=(random.randint(200, 230), random.randint(200, 230), random.randint(200, 230)))

        # 绘制文字（居中，使用大字号）
        # 计算每个字符的位置
        char_spacing = 45
        total_text_width = len(captcha_text) * char_spacing
        start_x = (width - total_text_width) // 2 + 10

        for i, char in enumerate(captcha_text):
            x = start_x + i * char_spacing
            y = random.randint(10, 25)

            # 如果是默认小字体，多次绘制来模拟大字体
            try:
                draw.text((x, y), char, font=font, fill=(random.randint(0, 100), random.randint(0, 100), random.randint(0, 100)))
            except:
                # 默认字体，绘制多次
                for dx in range(0, 30, 10):
                    for dy in range(0, 30, 10):
                        draw.text((x + dx, y + dy), char, font=font, fill=(random.randint(0, 100), random.randint(0, 100), random.randint(0, 100)))

        # 添加一些干扰点
        for _ in range(100):
            x = random.randint(0, width - 1)
            y = random.randint(0, height - 1)
            draw.point((x, y), fill=(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)))

        # 转换为base64
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        img_base64 = base64.b64encode(buffer.getvalue()).decode()

        # 生成验证码key并保存到缓存
        captcha_key = str(uuid.uuid4())
        captcha_cache[captcha_key] = {
            'code': captcha_text,
            'expire': int(time.time()) + 300  # 5分钟过期
        }

        # 清理过期缓存
        current_time = int(time.time())
        expired_keys = [k for k, v in captcha_cache.items() if v['expire'] < current_time]
        for k in expired_keys:
            del captcha_cache[k]

        return jsonify({
            'success': True,
            'image': f'data:image/png;base64,{img_base64}',
            'captcha_key': captcha_key
        })

    except ImportError as e:
        logger.error(f"PIL 库未安装: {str(e)}")
        return jsonify({'success': False, 'message': '请先安装 Pillow 库: pip install Pillow'}), 500
    except Exception as e:
        logger.error(f"生成验证码失败: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'message': f'生成验证码失败: {str(e)}'}), 500


@app.route('/api/auth/send-code', methods=['POST'])
def send_code():
    """发送验证码"""
    try:
        data = request.json
        logger.info(f"收到 send-code 请求: {data}")

        email = data.get('email', '').strip().lower()
        code_type = data.get('type', 'register')  # register 或 reset
        captcha_input = data.get('captcha', '').strip()  # 图形验证码
        captcha_key = data.get('captcha_key', '')

        logger.info(f"captcha_input: '{captcha_input}', captcha_key: '{captcha_key}'")

        # 验证邮箱格式
        import re
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, email):
            return jsonify({'success': False, 'message': '邮箱格式不正确'}), 400

        # 验证图形验证码
        if not captcha_input or not captcha_key:
            logger.error(f"验证码缺失: captcha_input='{captcha_input}', captcha_key='{captcha_key}'")
            return jsonify({'success': False, 'message': '请输入图形验证码', 'field': 'captcha'}), 400

        # 从缓存中验证图形验证码
        if captcha_key not in captcha_cache:
            return jsonify({'success': False, 'message': '验证码已过期，请刷新', 'field': 'captcha'}), 400

        cached_captcha = captcha_cache[captcha_key]
        if cached_captcha['expire'] < int(time.time()):
            del captcha_cache[captcha_key]
            return jsonify({'success': False, 'message': '验证码已过期，请刷新', 'field': 'captcha'}), 400

        # 验证验证码是否正确
        if captcha_input != cached_captcha['code']:
            return jsonify({'success': False, 'message': '图形验证码错误', 'field': 'captcha'}), 400

        # 验证成功后删除缓存（一次性使用）
        del captcha_cache[captcha_key]

        # 如果是注册类型，检查邮箱是否已注册
        if code_type == 'register':
            existing_user = get_user_by_email(email)
            if existing_user:
                return jsonify({'success': False, 'message': '该邮箱已注册，请直接登录', 'field': 'email', 'exists': True}), 400

        # 检查发送频率限制
        if not check_code_send_limit(email, code_type, limit_seconds=60):
            return jsonify({'success': False, 'message': '验证码发送过于频繁，请60秒后再试'}), 429

        # 生成邮箱验证码
        code = generate_verification_code()

        # 保存到数据库
        if not save_verification_code(email, code, code_type):
            return jsonify({'success': False, 'message': '验证码保存失败'}), 500

        # 发送验证码邮件
        if not send_verification_code(email, code):
            return jsonify({'success': False, 'message': '验证码发送失败，请稍后重试'}), 500

        # 返回成功
        return jsonify({
            'success': True,
            'message': '验证码已发送到您的邮箱'
        })

    except Exception as e:
        logger.error(f"发送验证码异常: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/auth/register', methods=['POST'])
def register():
    """用户注册"""
    try:
        data = request.json
        email = data.get('email', '').strip().lower()
        code = data.get('code', '').strip()
        nickname = data.get('nickname', '').strip()
        password = data.get('password', '').strip()
        encrypted = data.get('encrypted', False)

        # 如果密码已加密，先解密
        if encrypted:
            try:
                password = decrypt_client_password(password)
            except Exception as e:
                return jsonify({'success': False, 'message': '密码解密失败'}), 400

        # 验证参数
        if not all([email, code, nickname, password]):
            return jsonify({'success': False, 'message': '请填写完整信息'}), 400

        # 验证邮箱格式
        import re
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, email):
            return jsonify({'success': False, 'message': '邮箱格式不正确'}), 400

        # 验证密码长度
        if len(password) < 6:
            return jsonify({'success': False, 'message': '密码至少6位'}), 400

        # 验证验证码
        if not verify_code(email, code, 'register'):
            return jsonify({'success': False, 'message': '验证码错误或已过期'}), 400

        # 检查邮箱是否已注册
        if get_user_by_email(email):
            return jsonify({'success': False, 'message': '该邮箱已注册'}), 400

        # 直接使用明文密码存储
        user_id = create_user(email, password, nickname)
        if not user_id:
            return jsonify({'success': False, 'message': '注册失败'}), 500

        # 生成token
        access_token = generate_access_token(user_id)
        refresh_token = generate_refresh_token(user_id)

        # 保存token
        from datetime import datetime, timedelta
        expires_at = (datetime.now() + timedelta(hours=2)).strftime('%Y-%m-%d %H:%M:%S')
        save_user_token(user_id, access_token, expires_at)

        return jsonify({
            'success': True,
            'message': '注册成功',
            'user': {
                'id': user_id,
                'email': email,
                'nickname': nickname
            },
            'token': access_token,
            'refresh_token': refresh_token
        })

    except Exception as e:
        logger.error(f"注册异常: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/auth/login', methods=['POST'])
def login():
    """用户登录"""
    try:
        data = request.json
        email = data.get('email', '').strip().lower()
        password = data.get('password', '').strip()
        encrypted = data.get('encrypted', False)

        # 如果密码已加密，先解密
        if encrypted:
            try:
                password = decrypt_client_password(password)
            except Exception as e:
                return jsonify({'success': False, 'message': '密码解密失败'}), 400

        # 验证参数
        if not all([email, password]):
            return jsonify({'success': False, 'message': '请填写邮箱和密码'}), 400

        # 查找用户
        user = get_user_by_email(email)
        if not user:
            return jsonify({'success': False, 'message': '邮箱或密码错误'}), 401

        # 检查用户状态
        if not user['is_active']:
            return jsonify({'success': False, 'message': '账号已被禁用'}), 403

        # 验证密码（明文比较）
        if password != user['password']:
            return jsonify({'success': False, 'message': '邮箱或密码错误'}), 401

        # 生成token
        access_token = generate_access_token(user['id'])
        refresh_token = generate_refresh_token(user['id'])

        # 保存token
        from datetime import datetime, timedelta
        expires_at = (datetime.now() + timedelta(hours=2)).strftime('%Y-%m-%d %H:%M:%S')
        save_user_token(user['id'], access_token, expires_at)

        return jsonify({
            'success': True,
            'message': '登录成功',
            'user': {
                'id': user['id'],
                'email': user['email'],
                'nickname': user['nickname'],
                'is_admin': bool(user['is_admin'])
            },
            'token': access_token,
            'refresh_token': refresh_token
        })

    except Exception as e:
        logger.error(f"登录异常: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/auth/logout', methods=['POST'])
@require_auth
def logout():
    """用户登出"""
    try:
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        delete_user_token(token)
        return jsonify({'success': True, 'message': '登出成功'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/auth/refresh', methods=['POST'])
def refresh_token():
    """刷新access token"""
    try:
        data = request.json
        refresh_token = data.get('refresh_token')

        if not refresh_token:
            return jsonify({'success': False, 'message': '缺少refresh_token'}), 400

        # 验证refresh token
        from auth_utils import verify_token, generate_access_token
        payload = verify_token(refresh_token)

        if not payload:
            return jsonify({'success': False, 'message': 'Refresh Token无效或已过期'}), 401

        # 检查token类型
        if payload.get('type') != 'refresh':
            return jsonify({'success': False, 'message': 'Token类型错误'}), 401

        user_id = payload['user_id']

        # 检查用户是否仍然有效
        from database import get_user_by_id
        user = get_user_by_id(user_id)
        if not user or not user.get('is_active'):
            return jsonify({'success': False, 'message': '用户不存在或已被禁用'}), 401

        # 生成新的access token
        new_access_token = generate_access_token(user_id)

        # 保存新的access token
        from datetime import datetime, timedelta
        expires_at = (datetime.now() + timedelta(hours=2)).strftime('%Y-%m-%d %H:%M:%S')
        save_user_token(user_id, new_access_token, expires_at)

        return jsonify({
            'success': True,
            'token': new_access_token,
            'message': 'Token刷新成功'
        })

    except Exception as e:
        logger.error(f"刷新token异常: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500

# ============ 卡密模板管理 API ============

@app.route('/api/card-templates', methods=['GET'])
@require_admin
def get_card_templates_api():
    """获取所有卡密模板"""
    try:
        templates = get_all_templates()
        # 解析JSON字段
        for template in templates:
            template['channel_pool'] = json.loads(template['channel_pool'])
            if template['category_filter']:
                template['category_filter'] = json.loads(template['category_filter'])
        return jsonify({'success': True, 'templates': templates})
    except Exception as e:
        logger.error(f"获取卡密模板失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/card-templates/<int:template_id>', methods=['GET'])
@require_admin
def get_card_template_api(template_id):
    """获取单个卡密模板详情"""
    try:
        template = get_template_by_id(template_id)
        if not template:
            return jsonify({'success': False, 'error': '模板不存在'}), 404

        # 解析JSON字段
        template['channel_pool'] = json.loads(template['channel_pool'])
        if template['category_filter']:
            template['category_filter'] = json.loads(template['category_filter'])

        return jsonify({'success': True, 'template': template})
    except Exception as e:
        logger.error(f"获取卡密模板详情失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/card-templates', methods=['POST'])
@require_admin
def create_card_template_api():
    """创建卡密模板"""
    try:
        data = request.json
        name = data.get('name')
        channel_pool = data.get('channel_pool', [])
        max_channels = data.get('max_channels')
        validity_days = data.get('validity_days')
        category_filter = data.get('category_filter')

        if not all([name, channel_pool, max_channels is not None, validity_days is not None]):
            return jsonify({'success': False, 'error': '缺少必要参数'}), 400

        template_id = create_template(name, channel_pool, max_channels, validity_days, category_filter)
        return jsonify({
            'success': True,
            'message': '模板创建成功',
            'template_id': template_id
        })
    except Exception as e:
        logger.error(f"创建卡密模板失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/card-templates/<int:template_id>', methods=['PUT'])
@require_admin
def update_card_template_api(template_id):
    """更新卡密模板"""
    try:
        data = request.json
        update_template(
            template_id=template_id,
            name=data.get('name'),
            channel_pool=data.get('channel_pool'),
            max_channels=data.get('max_channels'),
            validity_days=data.get('validity_days'),
            category_filter=data.get('category_filter'),
            is_active=data.get('is_active')
        )
        return jsonify({'success': True, 'message': '模板更新成功'})
    except Exception as e:
        logger.error(f"更新卡密模板失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/card-templates/<int:template_id>', methods=['DELETE'])
@require_admin
def delete_card_template_api(template_id):
    """删除卡密模板"""
    try:
        delete_template(template_id)
        return jsonify({'success': True, 'message': '模板删除成功'})
    except Exception as e:
        logger.error(f"删除卡密模板失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ============ 卡密管理 API ============

@app.route('/api/card-codes', methods=['GET'])
@require_admin
def get_card_codes_api():
    """获取卡密列表（分页）"""
    try:
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 20))
        template_id = request.args.get('template_id')
        is_activated = request.args.get('is_activated')
        search = request.args.get('search')

        # 转换参数类型
        if is_activated is not None:
            is_activated = is_activated.lower() in ['true', '1', 'yes']

        result = get_all_cards(page, per_page, template_id, is_activated, search)
        return jsonify({'success': True, **result})
    except Exception as e:
        logger.error(f"获取卡密列表失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/card-codes/generate', methods=['POST'])
@require_admin
def generate_card_codes_api():
    """批量生成卡密"""
    try:
        data = request.json
        template_id = data.get('template_id')
        count = data.get('count', 1)

        if not template_id:
            return jsonify({'success': False, 'error': '缺少模板ID'}), 400

        if not isinstance(count, int) or count < 1 or count > 1000:
            return jsonify({'success': False, 'error': '生成数量必须在1-1000之间'}), 400

        cards = generate_cards(template_id, count)
        if not cards:
            return jsonify({'success': False, 'error': '模板不存在'}), 404

        return jsonify({
            'success': True,
            'message': f'成功生成{len(cards)}个卡密',
            'cards': cards
        })
    except Exception as e:
        logger.error(f"生成卡密失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/card-codes/<int:card_id>', methods=['DELETE'])
@require_admin
def delete_card_code_api(card_id):
    """删除卡密"""
    try:
        delete_card(card_id)
        return jsonify({'success': True, 'message': '卡密删除成功'})
    except Exception as e:
        logger.error(f"删除卡密失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/card-codes/<int:card_id>', methods=['PUT'])
@require_admin
def update_card_code_api(card_id):
    """修改卡密信息"""
    try:
        data = request.json
        # 允许修改绑定账号和激活状态
        update_card_activation(
            card_id=card_id,
            bound_account=data.get('bound_account'),
            is_activated=data.get('is_activated')
        )
        return jsonify({'success': True, 'message': '卡密更新成功'})
    except Exception as e:
        logger.error(f"更新卡密失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ============ 用户端卡密激活 API ============

@app.route('/api/user/available-templates', methods=['GET'])
@require_auth
def get_available_templates_api():
    """获取可用的卡密模板列表（仅启用的）"""
    try:
        templates = get_all_templates()
        # 只返回启用的模板
        active_templates = [t for t in templates if t.get('is_active') == 1]

        # 解析JSON字段
        for template in active_templates:
            template['channel_pool'] = json.loads(template['channel_pool'])
            if template['category_filter']:
                template['category_filter'] = json.loads(template['category_filter'])

        return jsonify({'success': True, 'templates': active_templates})
    except Exception as e:
        logger.error(f"获取可用模板失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/user/verify-card', methods=['POST'])
@require_auth
def verify_card_code_api():
    """验证卡密并返回可选频道"""
    try:
        user_id = request.user_id
        code = request.json.get('code')

        if not code:
            return jsonify({'success': False, 'error': '请输入卡密'}), 400

        # 查询卡密
        card = get_card_by_code(code)
        if not card:
            return jsonify({'success': False, 'error': '卡密不存在'}), 404

        # 检查是否已激活
        if card['is_activated']:
            if card['bound_user_id'] == user_id:
                return jsonify({'success': False, 'error': '该卡密已使用'})
            else:
                return jsonify({'success': False, 'error': '该卡密已被他人使用'})

        # 获取模板信息
        template = get_template_by_id(card['template_id'])
        if not template or template.get('is_active') != 1:
            return jsonify({'success': False, 'error': '卡密模板不存在或已停用'}), 404

        # 获取频道池中的所有频道
        channel_pool = json.loads(template['channel_pool'])
        available_channels = []
        for channel_id in channel_pool:
            channel = get_channel(channel_id)
            if channel:
                available_channels.append({
                    'id': channel['id'],
                    'name': channel['name'],
                    'avatar': channel.get('avatar'),
                    'type': channel.get('type', 'public')
                })

        return {
            'success': True,
            'template': {
                'id': template['id'],
                'name': template['name'],
                'max_channels': template['max_channels'],
                'validity_days': template['validity_days']
            },
            'available_channels': available_channels
        }
    except Exception as e:
        logger.error(f"验证卡密失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/user/activate-card', methods=['POST'])
@require_auth
def activate_card_code_api():
    """激活卡密并订阅频道"""
    try:
        user_id = request.user_id
        code = request.json.get('code')
        selected_channels = request.json.get('selected_channels', [])

        if not code:
            return jsonify({'success': False, 'error': '请输入卡密'}), 400

        # 1. 重新验证卡密
        card = get_card_by_code(code)
        if not card:
            return jsonify({'success': False, 'error': '卡密不存在'})

        if card['is_activated']:
            if card['bound_user_id'] == user_id:
                return jsonify({'success': False, 'error': '该卡密已使用'})
            else:
                return jsonify({'success': False, 'error': '该卡密已被他人使用'})

        # 2. 获取模板信息
        template = get_template_by_id(card['template_id'])
        if not template:
            return jsonify({'success': False, 'error': '模板不存在'})

        # 3. 验证选择的频道数量
        if len(selected_channels) > template['max_channels']:
            return jsonify({'success': False, 'error': f'最多只能选择{template["max_channels"]}个频道'}), 400

        # 4. 验证选择的频道是否在频道池中
        channel_pool = json.loads(template['channel_pool'])
        # 统一转为字符串进行比较（channel_pool中的ID可能是字符串）
        selected_channels_str = [str(ch_id) for ch_id in selected_channels]
        channel_pool_str = [str(ch_id) for ch_id in channel_pool]
        for ch_id in selected_channels_str:
            if ch_id not in channel_pool_str:
                return jsonify({'success': False, 'error': f'频道不在可选范围内'}), 400

        # 保存为字符串数组供后续使用
        selected_channels = selected_channels_str

        # 5. 计算失效时间
        from datetime import datetime, timedelta
        expires_at = datetime.now() + timedelta(days=template['validity_days'])

        # 6. 获取用户信息
        user = get_user_by_id(user_id)
        bound_account = user['email'] if user else None

        # 7. 更新卡密状态
        update_card_activation(
            card_id=card['id'],
            is_activated=1,
            activated_at=datetime.now(),
            expires_at=expires_at,
            bound_user_id=user_id,
            bound_account=bound_account,
            selected_channels=selected_channels
        )

        # 8. 为用户自动订阅频道（权限自动分配）
        subscribe_channels(user_id, selected_channels)

        logger.info(f"用户 {user_id} 激活卡密 {code}，订阅了 {len(selected_channels)} 个频道")

        return {
            'success': True,
            'message': f'成功兑换{template["name"]}，已订阅{len(selected_channels)}个频道',
            'expires_at': expires_at.strftime('%Y-%m-%d %H:%M:%S')
        }
    except Exception as e:
        logger.error(f"激活卡密失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/user/subscriptions', methods=['GET'])
@require_auth
def get_user_subscriptions_api():
    """获取用户当前的所有订阅"""
    try:
        user_id = request.user_id

        # 获取用户已激活的卡密
        cards = get_user_cards(user_id)

        # 筛选出已激活且未过期的卡密
        from datetime import datetime
        now = datetime.now()
        subscriptions = []
        for card in cards:
            if card.get('is_activated') == 1 and card.get('expires_at'):
                expires_at = datetime.strptime(card['expires_at'], '%Y-%m-%d %H:%M:%S.%f')
                if expires_at > now:
                    subscriptions.append({
                        'card_id': card['id'],
                        'card_code': card['code'],
                        'template_name': card['template_name'],
                        'expires_at': card['expires_at'],
                        'selected_channels': json.loads(card['selected_channels']) if card.get('selected_channels') else []
                    })

        return jsonify({'success': True, 'subscriptions': subscriptions})
    except Exception as e:
        logger.error(f"获取用户订阅失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/user/my-cards', methods=['GET'])
@require_auth
def get_my_cards_api():
    """查看我的卡密列表"""
    try:
        user_id = request.user_id
        cards = get_user_cards(user_id)

        # 解析JSON字段
        for card in cards:
            if card.get('selected_channels'):
                card['selected_channels'] = json.loads(card['selected_channels'])

        return jsonify({'success': True, 'cards': cards})
    except Exception as e:
        logger.error(f"获取用户卡密失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/auth/me', methods=['GET'])
@require_auth
def get_current_user():
    """获取当前用户信息"""
    try:
        user_id = request.user_id
        user = get_user_by_id(user_id)

        if not user:
            return jsonify({'success': False, 'message': '用户不存在'}), 404

        return jsonify({
            'success': True,
            'user': {
                'id': user['id'],
                'email': user['email'],
                'nickname': user['nickname'],
                'is_admin': bool(user['is_admin']),
                'created_at': user['created_at']
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/auth/profile', methods=['PUT'])
@require_auth
def update_profile():
    """更新用户资料"""
    try:
        user_id = request.user_id
        data = request.json
        nickname = data.get('nickname', '').strip()

        if not nickname:
            return jsonify({'success': False, 'message': '昵称不能为空'}), 400

        if update_user(user_id, nickname=nickname):
            return jsonify({'success': True, 'message': '更新成功'})
        else:
            return jsonify({'success': False, 'message': '更新失败'}), 500

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# ============ 用户管理 API（管理员） ============

@app.route('/api/admin/users', methods=['GET'])
@require_admin
def admin_get_users():
    """获取用户列表"""
    try:
        limit = int(request.args.get('limit', 50))
        offset = int(request.args.get('offset', 0))
        search = request.args.get('search', '').strip()

        result = get_all_users(limit=limit, offset=offset, search=search)

        # 为每个用户添加卡密信息
        for user in result['users']:
            try:
                # 获取用户最近激活的卡密
                cards = get_user_cards(user['id'])
                if cards and len(cards) > 0:
                    # 找到最新的激活卡密
                    latest_card = None
                    latest_time = None

                    for card in cards:
                        if card.get('is_activated') == 1 and card.get('activated_at'):
                            if not latest_time or card['activated_at'] > latest_time:
                                latest_time = card['activated_at']
                                latest_card = card

                    if latest_card:
                        # 计算剩余天数
                        from datetime import datetime
                        expires_at = datetime.strptime(latest_card['expires_at'], '%Y-%m-%d %H:%M:%S.%f')
                        now = datetime.now()
                        days_left = (expires_at - now).days

                        user['card_info'] = {
                            'code': latest_card['code'],
                            'template_name': latest_card['template_name'],
                            'days_left': days_left
                        }
                    else:
                        user['card_info'] = None
                else:
                    user['card_info'] = None
            except Exception as e:
                logger.error(f"获取用户{user['id']}卡密信息失败: {e}")
                user['card_info'] = None

        return jsonify({
            'success': True,
            'data': result
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/admin/users', methods=['POST'])
@require_admin
def admin_create_user():
    """管理员创建用户（不需要邮箱验证码）"""
    try:
        data = request.json
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')
        nickname = data.get('nickname', '').strip()
        is_admin = data.get('is_admin', 0)
        is_active = data.get('is_active', 1)

        # 验证
        if not email:
            return jsonify({'success': False, 'message': '邮箱不能为空'}), 400
        if not password:
            return jsonify({'success': False, 'message': '密码不能为空'}), 400
        if not nickname:
            return jsonify({'success': False, 'message': '昵称不能为空'}), 400

        # 检查邮箱是否已存在
        existing_user = get_user_by_email(email)
        if existing_user:
            return jsonify({'success': False, 'message': '该邮箱已被注册'}), 400

        # 直接使用明文密码存储
        user_id = create_user(
            email=email,
            password=password,
            nickname=nickname,
            is_admin=is_admin,
            is_active=is_active
        )

        if user_id:
            return jsonify({
                'success': True,
                'message': '创建成功',
                'user_id': user_id
            })
        else:
            return jsonify({'success': False, 'message': '创建失败'}), 500

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/admin/users/<int:user_id>', methods=['GET'])
@require_admin
def admin_get_user(user_id):
    """获取用户详情"""
    try:
        user = get_user_by_id(user_id)
        if not user:
            return jsonify({'success': False, 'message': '用户不存在'}), 404

        # 密码明文存储，直接返回
        password = user['password']

        return jsonify({
            'success': True,
            'user': {
                'id': user['id'],
                'email': user['email'],
                'password': password,  # 明文密码供管理员查看
                'nickname': user['nickname'],
                'is_admin': bool(user['is_admin']),
                'is_active': bool(user['is_active']),
                'created_at': user['created_at'],
                'updated_at': user.get('updated_at')  # 使用get方法避免KeyError
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/admin/users/<int:user_id>', methods=['PUT'])
@require_admin
def admin_update_user(user_id):
    """更新用户信息"""
    try:
        data = request.json
        email = data.get('email')
        password = data.get('password')
        nickname = data.get('nickname')
        is_admin = data.get('is_admin')
        is_active = data.get('is_active')

        # 检查邮箱是否被其他用户占用
        if email:
            existing_user = get_user_by_email(email)
            if existing_user and existing_user['id'] != user_id:
                return jsonify({'success': False, 'message': '该邮箱已被其他用户使用'}), 400

        # 更新用户信息（支持可选字段）
        if update_user(user_id, email=email, password=password, nickname=nickname, is_admin=is_admin, is_active=is_active):
            return jsonify({'success': True, 'message': '更新成功'})
        else:
            return jsonify({'success': False, 'message': '用户不存在'}), 404

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/admin/users/<int:user_id>', methods=['DELETE'])
@require_admin
def admin_delete_user(user_id):
    """删除用户"""
    try:
        # 不能删除自己
        if request.user_id == user_id:
            return jsonify({'success': False, 'message': '不能删除自己'}), 400

        if delete_user(user_id):
            return jsonify({'success': True, 'message': '删除成功'})
        else:
            return jsonify({'success': False, 'message': '用户不存在'}), 404

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

# ============ 后台定时任务 ============

def cleanup_job():
    """清理过期会话的定时任务"""
    try:
        logger.info("=" * 60)
        logger.info("开始执行定时清理任务 (保留7天内的数据)")
        logger.info(f"执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        deleted_count = cleanup_old_sessions(7)

        logger.info(f"✓ 清理完成")
        logger.info(f"  删除记录数: {deleted_count}")
        logger.info(f"  保留天数: 7天")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"✗ 定时清理任务失败: {e}")
        import traceback
        logger.error(traceback.format_exc())

# ============ 推送设置API ============

@app.route('/api/push/settings', methods=['GET'])
@require_admin
def get_push_settings_api():
    """获取推送设置"""
    try:
        settings = get_push_settings()
        return jsonify({
            'success': True,
            'settings': settings
        })
    except Exception as e:
        logger.error(f"获取推送设置失败: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/push/settings', methods=['POST'])
@require_admin
def update_push_settings_api():
    """更新推送设置"""
    try:
        data = request.json
        mode = data.get('mode', 'all')
        switch_times = data.get('switch_times', [])
        interval_minutes = data.get('interval_minutes')

        if mode not in ['all', 'roundrobin']:
            return jsonify({'success': False, 'error': '无效的推送模式'}), 400

        # 验证时间点格式
        if switch_times:
            for time_str in switch_times:
                try:
                    hours, minutes = map(int, time_str.split(':'))
                    if not (0 <= hours < 24 and 0 <= minutes < 60):
                        raise ValueError()
                except:
                    return jsonify({'success': False, 'error': f'无效的时间格式: {time_str}'}), 400

        # 验证间隔分钟数
        if interval_minutes is not None:
            if not isinstance(interval_minutes, int) or interval_minutes < 1 or interval_minutes > 10080:  # 最多一周
                return jsonify({'success': False, 'error': '无效的间隔时间（1-10080分钟）'}), 400

        update_push_settings(mode, switch_times, interval_minutes)

        logger.info(f"推送设置已更新: mode={mode}, switch_times={switch_times}, interval_minutes={interval_minutes}")

        # 重新调度轮询任务
        reschedule_push_token_jobs()

        return jsonify({'success': True, 'message': '推送设置已保存'})

    except Exception as e:
        logger.error(f"更新推送设置失败: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/push/active-tokens', methods=['GET'])
@require_admin
def get_active_tokens_api():
    """获取当前活跃的推送令牌"""
    try:
        tokens = get_active_tokens_for_push()
        return jsonify({
            'success': True,
            'tokens': tokens
        })
    except Exception as e:
        logger.error(f"获取活跃令牌失败: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/messages/list', methods=['GET'])
@require_admin
def get_messages_list_api():
    """获取消息列表（支持筛选、搜索、分页）"""
    try:
        # 获取参数
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 20))
        channel_id = request.args.get('channel_id', '')
        channel_type = request.args.get('channel_type', '')
        category_id = request.args.get('category_id', '')
        token = request.args.get('token', '')
        is_filtered_str = request.args.get('is_filtered', '')
        search_content = request.args.get('search_content', '')

        # 处理 is_filtered 参数
        is_filtered = None
        if is_filtered_str == 'yes':
            is_filtered = True
        elif is_filtered_str == 'no':
            is_filtered = False

        # 调用数据库函数
        result = get_messages_list(
            page=page,
            per_page=per_page,
            channel_id=channel_id,
            channel_type=channel_type,
            category_id=category_id,
            token=token,
            is_filtered=is_filtered,
            search_content=search_content
        )

        return jsonify({
            'success': True,
            **result
        })

    except Exception as e:
        logger.error(f"获取消息列表失败: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ============ 定时任务 ============

def switch_push_token_job():
    """定时切换轮询推送的活跃令牌"""
    try:
        logger.info("=" * 60)
        logger.info("开始执行轮询令牌切换任务")
        logger.info(f"执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        settings = get_push_settings()

        if settings['mode'] == 'roundrobin':
            new_indices = switch_active_token()
            logger.info(f"轮询令牌索引已更新: {new_indices}")

            # 获取当前活跃的令牌信息
            active_tokens = get_active_tokens_for_push()
            if active_tokens:
                logger.info(f"当前活跃令牌数量: {len(active_tokens)}")
                for token in active_tokens:
                    logger.info(f"  - 频道 {token['channel_name']} ({token['channel_id']}): {token['token']}")

            logger.info("✓ 轮询令牌切换完成")
        else:
            logger.info("当前模式为全部推送，无需切换令牌")

        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"✗ 轮询令牌切换任务失败: {e}")
        import traceback
        logger.error(traceback.format_exc())

# 全局变量存储调度任务，用于重新调度
push_token_jobs = []

def reschedule_push_token_jobs():
    """重新调度轮询令牌切换任务（支持多时间点和间隔轮换）"""
    global push_token_jobs

    # 取消所有现有任务
    for job in push_token_jobs:
        schedule.cancel_job(job)
    push_token_jobs = []
    logger.info("已取消所有旧的轮询切换任务")

    # 获取新的设置
    settings = get_push_settings()

    if settings['mode'] != 'roundrobin':
        logger.info("当前模式不是轮询，不创建调度任务")
        return

    # 1. 创建固定时间点任务
    switch_times = settings.get('switch_times', [])
    for time_str in switch_times:
        job = schedule.every().day.at(time_str).do(switch_push_token_job)
        push_token_jobs.append(job)
        logger.info(f"已添加固定时间点调度: 每天{time_str}")

    # 2. 创建间隔时间任务
    interval_minutes = settings.get('interval_minutes')
    if interval_minutes:
        job = schedule.every(interval_minutes).minutes.do(switch_push_token_job)
        push_token_jobs.append(job)
        logger.info(f"已添加间隔时间调度: 每{interval_minutes}分钟")

    if not push_token_jobs:
        logger.warning("轮询模式下未配置任何轮换时间！")

def run_schedule():
    """运行定时任务调度器"""

    # 每天凌晨3点执行清理任务
    schedule.every().day.at("03:00").do(cleanup_job)

    # 轮询推送切换任务 - 初始调度（使用新函数）
    reschedule_push_token_jobs()

    logger.info("定时任务调度器已启动")
    logger.info("  - 清理任务: 每天凌晨3:00")
    logger.info("  - 轮询切换: 支持多时间点和间隔轮换（可配置）")

    while True:
        schedule.run_pending()
        time.sleep(60)  # 每分钟检查一次

if __name__ == '__main__':
    print('=' * 60)
    print('Flask API 服务启动')
    print('')
    print('内部 API:')
    print(f'  http://localhost:{FLASK_PORT}/api/send-message')
    print(f'  http://localhost:{FLASK_PORT}/api/tokens')
    print('')
    print('外部接口（推送消息到频道）:')
    print(f'  POST {PUSH_API_URL}?channel_token=xxx')
    print('')
    print('前端页面:', FRONTEND_URL)
    print('数据库:', DB_PATH)
    print('')
    print('定时任务:')
    print('  每天凌晨3:00清理过期会话 (保留7天)')
    print('=' * 60)

    # 启动后台定时任务线程
    scheduler_thread = threading.Thread(target=run_schedule, daemon=True)
    scheduler_thread.start()
    print('✓ 定时任务调度器已启动（后台线程）')

    # 启动Flask服务
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=True, use_reloader=False)
