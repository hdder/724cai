import sqlite3
from datetime import datetime
import os
import logging
import json

# 配置日志
logger = logging.getLogger(__name__)

# 数据库路径
DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'websocket', 'data', 'push_messages.db')

def get_db_connection():
    """获取数据库连接"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_database():
    """初始化数据库表结构（不创建初始数据）"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # 创建用户表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            nickname TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 创建验证码表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS verification_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            code TEXT NOT NULL,
            type TEXT NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            used INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 创建股票基础表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code VARCHAR(10) NOT NULL UNIQUE,
            name VARCHAR(50) NOT NULL,
            pinyin VARCHAR(100),
            pinyin_abbr VARCHAR(20),
            market VARCHAR(10),
            status INTEGER DEFAULT 1,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 创建股票同步日志表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stock_sync_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sync_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            total_count INTEGER,
            new_count INTEGER,
            update_count INTEGER,
            error_count INTEGER,
            status VARCHAR(20),
            error_message TEXT,
            duration_seconds INTEGER
        )
    """)

    # 创建用户会话表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token TEXT UNIQUE NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    # 检查并迁移 categories 表，添加 type 字段
    cursor.execute("PRAGMA table_info(categories)")
    columns = [column[1] for column in cursor.fetchall()]

    if 'type' not in columns:
        logger.info("检测到旧版 categories 表，正在添加 type 字段...")
        cursor.execute("ALTER TABLE categories ADD COLUMN type TEXT DEFAULT 'public'")
        logger.info("✓ categories 表已添加 type 字段")

    # 创建频道表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS channels (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT DEFAULT 'public',
            category TEXT,
            avatar TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 检查并添加 avatar 字段（兼容旧数据库）
    cursor.execute("PRAGMA table_info(channels)")
    columns = [column[1] for column in cursor.fetchall()]
    if 'avatar' not in columns:
        logger.info("检测到旧版 channels 表，正在添加 avatar 字段...")
        cursor.execute("ALTER TABLE channels ADD COLUMN avatar TEXT")
        logger.info("✓ channels 表已添加 avatar 字段")

    # 创建消息表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id TEXT NOT NULL,
            title TEXT,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (channel_id) REFERENCES channels(id)
        )
    """)

    # 创建消息索引
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_messages_channel_time
        ON messages(channel_id, created_at DESC)
    """)

    # 创建频道令牌表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS channel_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id TEXT NOT NULL,
            token TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (channel_id) REFERENCES channels(id)
        )
    """)

    # 迁移：为已存在的 channel_tokens 表添加 last_used_at 列
    try:
        cursor.execute("ALTER TABLE channel_tokens ADD COLUMN last_used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        print('✓ channel_tokens 表已添加 last_used_at 列')
    except Exception:
        pass  # 列已存在

    # 创建用户会话表(WebSocket连接)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_sessions (
            socket_id TEXT PRIMARY KEY,
            current_channel TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 创建用户订阅表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            socket_id TEXT NOT NULL,
            channel_id TEXT NOT NULL,
            subscribed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (socket_id) REFERENCES user_sessions(socket_id) ON DELETE CASCADE,
            UNIQUE(socket_id, channel_id)
        )
    """)

    # 创建标签表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            frequency INTEGER DEFAULT 50,
            type TEXT DEFAULT 'public',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 创建推送设置表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS push_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mode TEXT NOT NULL DEFAULT 'all',
            switch_times TEXT,  -- JSON: ["08:00", "14:00", "20:00"]
            interval_minutes INTEGER,  -- 间隔分钟数
            active_token_index INTEGER DEFAULT 0,
            roundrobin_indices TEXT DEFAULT '{}',  -- JSON: {"channel1": 0, "channel2": 1}
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 创建股票表索引
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_stocks_code ON stocks(code)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_stocks_pinyin ON stocks(pinyin)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_stocks_abbr ON stocks(pinyin_abbr)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_stocks_status ON stocks(status)")

    # 创建同步日志索引
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sync_time ON stock_sync_logs(sync_time)")

    conn.commit()
    conn.close()
    print('✓ 数据库表结构初始化完成（未创建初始数据）')

    # 初始化卡密表
    init_card_tables()

def init_channels(cursor):
    """初始化预设频道"""
    default_channels = {
        'channel1': {'name': '新闻资讯'},
        'channel2': {'name': '股票行情'},
        'channel3': {'name': '系统通知'},
        'channel4': {'name': '娱乐八卦'},
        'channel5': {'name': '科技前沿'}
    }

    for channel_id, info in default_channels.items():
        cursor.execute("""
            INSERT OR IGNORE INTO channels (id, name)
            VALUES (?, ?)
        """, (channel_id, info['name']))

    print('✓ 预设频道已初始化')

def init_tokens(cursor):
    """初始化预设令牌"""
    default_tokens = [
        {'channel_id': 'channel1', 'token': 'test_token_123'},
        {'channel_id': 'channel2', 'token': 'stock_token_xyz'},
        {'channel_id': 'channel3', 'token': 'system_token_456'},
        {'channel_id': 'channel4', 'token': 'ent_token_789'},
        {'channel_id': 'channel5', 'token': 'tech_token_def'}
    ]

    for token_info in default_tokens:
        cursor.execute("""
            INSERT OR IGNORE INTO channel_tokens (channel_id, token)
            VALUES (?, ?)
        """, (token_info['channel_id'], token_info['token']))

    print('✓ 预设令牌已初始化')

# ============ 频道管理 ============

def get_all_channels(order_by='id'):
    """获取所有频道

    Args:
        order_by: 排序方式，'id' 按ID排序，'latest_message' 按最新消息时间排序
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    if order_by == 'latest_message':
        # 按最新消息时间排序（LEFT JOIN获取最新消息时间）
        cursor.execute("""
            SELECT c.id, c.name, c.type, c.category_id, c.avatar,
                   COALESCE(MAX(m.created_at), '1970-01-01 00:00:00') as latest_message_time
            FROM channels c
            LEFT JOIN messages m ON c.id = m.channel_id
            GROUP BY c.id
            ORDER BY latest_message_time DESC, c.id ASC
        """)
    else:
        # 按ID排序保证分页一致性
        cursor.execute("SELECT id, name, type, category_id, avatar FROM channels ORDER BY id ASC")

    rows = cursor.fetchall()
    conn.close()

    # 如果是按最新消息排序，去掉临时字段
    if order_by == 'latest_message':
        return [dict(row) for row in rows]
    else:
        return [dict(row) for row in rows]

def get_channel(channel_id):
    """获取单个频道"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM channels WHERE id = ?", (channel_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def create_channel(channel_id, name, type='public', category='', avatar=None):
    """创建频道"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO channels (id, name, type, category_id, avatar)
            VALUES (?, ?, ?, ?, ?)
        """, (channel_id, name, type, category, avatar))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def delete_channel(channel_id):
    """删除频道及其所有关联的token和消息"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # 获取频道信息以获取头像路径
        cursor.execute("SELECT avatar FROM channels WHERE id = ?", (channel_id,))
        channel = cursor.fetchone()

        # 删除频道关联的所有token
        cursor.execute("DELETE FROM channel_tokens WHERE channel_id = ?", (channel_id,))
        # 删除频道的所有消息
        cursor.execute("DELETE FROM messages WHERE channel_id = ?", (channel_id,))
        # 删除频道记录
        cursor.execute("DELETE FROM channels WHERE id = ?", (channel_id,))
        conn.commit()

        # 删除头像备份文件
        if channel and channel['avatar']:
            try:
                # 头像备份路径
                import os
                backup_dir = os.path.join(os.path.dirname(__file__), '..', 'avatars')
                avatar_path = os.path.join(backup_dir, f"{channel_id}.png")

                # 如果存在备份文件，删除它
                if os.path.exists(avatar_path):
                    os.remove(avatar_path)
                    logger.info(f"已删除频道 {channel_id} 的头像备份文件")
            except Exception as e:
                logger.error(f"删除头像备份文件失败: {e}")

        return True
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def get_next_channel_id():
    """获取下一个频道ID（自增数字）"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT CAST(id AS INTEGER) FROM channels WHERE id LIKE '%[^0-9]%' ESCAPE '^'")
    # 更简单的方法：直接找最大的数字ID
    cursor.execute("""
        SELECT id FROM channels
        WHERE id GLOB '*[0-9]*'
        ORDER BY CAST(id AS INTEGER) DESC
        LIMIT 1
    """)
    row = cursor.fetchone()
    conn.close()

    if row and row['id'].isdigit():
        return str(int(row['id']) + 1)
    else:
        return '1'  # 第一个频道

# ============ 消息管理 ============

def parse_sqlite_timestamp(timestamp_str):
    """将SQLite时间戳字符串转换为毫秒时间戳

    兼容处理：
    - 旧数据：UTC时间（CURRENT_TIMESTAMP默认）
    - 新数据：本地CST时间（save_message中使用datetime.now()）

    格式: "2026-04-17 11:52:00"
    """
    if not timestamp_str:
        return None

    try:
        from datetime import datetime

        # 简单解析为本地时间
        # 格式: "YYYY-MM-DD HH:MM:SS"
        parts = timestamp_str.split(' ')
        date_part = parts[0]  # "2026-04-17"
        time_part = parts[1] if len(parts) > 1 else "00:00:00"  # "11:52:00"

        date_parts = date_part.split('-')
        time_parts = time_part.split(':')

        year = int(date_parts[0])
        month = int(date_parts[1])
        day = int(date_parts[2])
        hour = int(time_parts[0]) if len(time_parts) > 0 else 0
        minute = int(time_parts[1]) if len(time_parts) > 1 else 0
        second = int(time_parts[2]) if len(time_parts) > 2 else 0

        # 创建本地时间的datetime对象
        dt = datetime(year, month, day, hour, minute, second)

        # 转换为毫秒时间戳
        return int(dt.timestamp() * 1000)
    except Exception as e:
        logger.error(f"解析时间戳失败: {timestamp_str}, 错误: {e}")
        return None

def save_message(channel_id, title, content, token=''):
    """保存消息"""
    from datetime import datetime
    # 使用本地时间（CST）而不是UTC
    local_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO messages (channel_id, content, token, timestamp, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (channel_id, content, token, local_time, local_time))
    conn.commit()
    message_id = cursor.lastrowid
    conn.close()
    return message_id

def update_message_doubao(message_id, doubao_result):
    """更新消息的豆包AI分析结果"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE messages SET doubao_ai = ? WHERE id = ?
    """, (doubao_result, message_id))
    conn.commit()
    conn.close()

def get_channel_doubao_summary(channel_id, offset=0, limit=10):
    """获取频道的豆包AI分析消息列表（分页）

    Args:
        channel_id: 频道ID
        offset: 偏移量（从第几条开始，默认0）
        limit: 每次获取多少条（默认10条）

    Returns:
        dict: {
            'messages': [...],
            'offset': 当前偏移量,
            'limit': 每页数量,
            'total': 总数量,
            'has_more': 是否还有更多
        }
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # 先获取总数
    cursor.execute("""
        SELECT COUNT(*)
        FROM messages
        WHERE channel_id = ? AND doubao_ai IS NOT NULL AND doubao_ai != ''
    """, (channel_id,))
    total = cursor.fetchone()[0]

    # 获取分页数据（按时间倒序，最新的在前）
    cursor.execute("""
        SELECT id, content, doubao_ai, created_at
        FROM messages
        WHERE channel_id = ? AND doubao_ai IS NOT NULL AND doubao_ai != ''
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
    """, (channel_id, limit, offset))

    rows = cursor.fetchall()
    conn.close()

    messages_list = []

    for row in rows:
        try:
            msg_id = row[0]
            content = row[1]
            doubao_ai = row[2]
            created_at = row[3]

            # 解析豆包AI分析结果
            doubao_data = json.loads(doubao_ai)
            stock_list = doubao_data.get('stock_list', [])

            # 只保留有股票识别的消息
            if stock_list:
                messages_list.append({
                    'id': msg_id,
                    'content': content,  # 完整消息内容
                    'timestamp': created_at,
                    'stocks': stock_list
                })
        except (json.JSONDecodeError, KeyError):
            continue

    return {
        'messages': messages_list,
        'offset': offset + len(messages_list),  # 下次的offset
        'limit': limit,
        'total': total,
        'has_more': (offset + len(messages_list)) < total
    }

def get_tokens_last_message_time():
    """获取所有token的最后消息时间

    Returns:
        dict: {token: '2026-04-21 13:04:56'}
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # 查询每个token的最新消息时间
    cursor.execute("""
        SELECT token, MAX(created_at) as last_time
        FROM messages
        WHERE token IS NOT NULL AND token != ''
        GROUP BY token
    """)

    result = {row['token']: row['last_time'] for row in cursor.fetchall()}
    conn.close()
    return result

def get_channel_messages(channel_id, limit=50, offset=0, last_loaded_timestamp=None):
    """获取频道消息 - 支持分页

    Args:
        channel_id: 频道ID
        limit: 每页数量（默认50条）
        offset: 偏移量（0表示从最新消息开始）
        last_loaded_timestamp: 上一次加载的第一条消息的时间戳（用于判断日期分割线）

    Returns:
        {
            'messages': [...],  # 正序：旧消息在前，新消息在后
            'total': 100,       # 总消息数
            'loaded': 50,       # 已加载消息数
            'has_more': True    # 是否还有更早的消息
        }
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, channel_id, content, created_at, doubao_ai
        FROM messages
        WHERE channel_id = ?
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
    """, (channel_id, limit, offset))
    rows = cursor.fetchall()
    conn.close()

    # 反转为正序（旧消息在前，新消息在后）
    messages = []
    for i, row in enumerate(reversed(rows)):
        msg = dict(row)
        # 将 created_at 转换为毫秒时间戳（前端期望的格式）
        created_at_str = msg.pop('created_at')
        # SQLite的CURRENT_TIMESTAMP返回格式: "2026-04-17 11:52:00" (UTC时间)
        # 解析并转换为毫秒时间戳
        msg['timestamp'] = parse_sqlite_timestamp(created_at_str)

        # 判断是否需要显示日期分割线
        msg['show_date_separator'] = False

        if i == 0:
            # 第一条消息：检查是否与已加载的最后一条消息日期相同
            if last_loaded_timestamp is not None:
                from datetime import datetime
                last_date = datetime.fromtimestamp(last_loaded_timestamp / 1000)
                curr_date = datetime.fromtimestamp(msg['timestamp'] / 1000)

                # 如果日期不同，显示分割线
                if (last_date.year != curr_date.year or
                    last_date.month != curr_date.month or
                    last_date.day != curr_date.day):
                    msg['show_date_separator'] = True
                # 否则不显示（同一天）
            # else：初始加载，不显示分割线（只有跨日期才显示）
        elif i > 0:
            # 检查与前一条消息的日期是否不同
            prev_timestamp = messages[i-1]['timestamp']
            curr_timestamp = msg['timestamp']

            from datetime import datetime
            prev_date = datetime.fromtimestamp(prev_timestamp / 1000)
            curr_date = datetime.fromtimestamp(curr_timestamp / 1000)

            # 比较年月日
            if (prev_date.year != curr_date.year or
                prev_date.month != curr_date.month or
                prev_date.day != curr_date.day):
                msg['show_date_separator'] = True

        messages.append(msg)

    # 获取该频道的总消息数
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as total FROM messages WHERE channel_id = ?", (channel_id,))
    total = cursor.fetchone()['total']
    conn.close()

    return {
        'messages': messages,
        'total': total,
        'loaded': len(messages) + offset,
        'has_more': len(messages) + offset < total  # 是否还有更早的消息
    }

def get_channels_latest_messages_batch(channel_ids):
    """批量获取多个频道的最新消息（性能优化：一次查询代替N次）

    Args:
        channel_ids: 频道ID列表

    Returns:
        {channel_id: {'content': '...', 'timestamp': 123}, ...}
    """
    if not channel_ids:
        return {}

    conn = get_db_connection()
    cursor = conn.cursor()

    # 单次查询获取所有频道的最新消息
    placeholders = ','.join(['?' for _ in channel_ids])
    query = f"""
        SELECT m.channel_id, m.content, m.created_at
        FROM messages m
        INNER JOIN (
            SELECT channel_id, MAX(id) as max_id
            FROM messages
            WHERE channel_id IN ({placeholders})
            GROUP BY channel_id
        ) latest ON m.id = latest.max_id
    """

    cursor.execute(query, channel_ids)
    rows = cursor.fetchall()
    conn.close()

    # 构建结果字典
    result = {}
    for row in rows:
        channel_id = row['channel_id']
        content = row['content']
        created_at_str = row['created_at']

        # 处理图片和文件标记，替换为文本描述
        import re
        # 替换图片标记 ![alt](url) 为 [图片]
        content = re.sub(r'!\[.*?\]\(.*?\)', '[图片]', content)
        # 替换文件标记 [文件](url) 或 [附件](url) 为 [文件]
        content = re.sub(r'\[.*?(文件|附件).*?\]\(.*?\)', '[文件]', content)

        # 清理多余空行
        content = re.sub(r'\n+', '\n', content).strip()

        # 截断content为50字符（减少网络传输）
        if len(content) > 50:
            content = content[:50] + '...'

        result[channel_id] = {
            'content': content,
            'timestamp': parse_sqlite_timestamp(created_at_str)
        }

    return result

def get_message_by_id(message_id):
    """获取单条消息的完整内容"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, channel_id, title, content, created_at, doubao_ai
        FROM messages
        WHERE id = ?
    """, (message_id,))
    row = cursor.fetchone()
    conn.close()

    if row:
        return {
            'id': row[0],
            'channel_id': row[1],
            'title': row[2],
            'content': row[3],
            'created_at': row[4],
            'doubao_ai': row[5]
        }
    return None

def get_stats():
    """获取统计信息"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            COUNT(DISTINCT channel_id) as channel_count,
            COUNT(*) as total_messages
        FROM messages
    """)
    row = cursor.fetchone()
    conn.close()
    return {
        'channel_count': row['channel_count'],
        'total_messages': row['total_messages']
    }

def cleanup_old_messages(channel_id, keep=100):
    """清理旧消息"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        DELETE FROM messages
        WHERE channel_id = ?
        AND id NOT IN (
            SELECT id FROM messages
            WHERE channel_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        )
    """, (channel_id, channel_id, keep))
    deleted_count = cursor.rowcount
    conn.commit()
    conn.close()
    return deleted_count

# ============ 令牌管理 ============

def get_all_tokens():
    """获取所有令牌"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT channel_id, token FROM channel_tokens")
    rows = cursor.fetchall()
    conn.close()
    # 转换为 { token: channel_id } 格式
    return {row['token']: row['channel_id'] for row in rows}

def get_channel_by_token(token):
    """根据令牌获取频道ID"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT channel_id FROM channel_tokens WHERE token = ?", (token,))
    row = cursor.fetchone()
    conn.close()
    return row['channel_id'] if row else None

def add_token(channel_id, token):
    """添加令牌"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO channel_tokens (channel_id, token)
            VALUES (?, ?)
        """, (channel_id, token))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def delete_token(token):
    """删除令牌"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM channel_tokens WHERE token = ?", (token,))
    deleted_count = cursor.rowcount
    conn.commit()
    conn.close()
    return deleted_count > 0

def update_tokens(tokens_dict):
    """批量更新令牌（删除所有后重新插入）"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # 删除所有现有令牌
        cursor.execute("DELETE FROM channel_tokens")
        # 重新插入
        for token, channel_id in tokens_dict.items():
            cursor.execute("""
                INSERT INTO channel_tokens (channel_id, token)
                VALUES (?, ?)
            """, (channel_id, token))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

# ============ 用户会话管理 ============

def create_session(socket_id, user_id=None):
    """创建新用户会话"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO user_sessions (socket_id, user_id)
        VALUES (?, ?)
    """, (socket_id, user_id))
    conn.commit()
    conn.close()

def update_session_activity(socket_id):
    """更新会话活动时间"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE user_sessions
        SET last_active = CURRENT_TIMESTAMP
        WHERE socket_id = ?
    """, (socket_id,))
    conn.commit()
    conn.close()

def delete_session(socket_id):
    """删除会话(级联删除订阅)"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM user_sessions WHERE socket_id = ?", (socket_id,))
    conn.commit()
    conn.close()

def cleanup_old_sessions(days=7):
    """清理N天前的过期会话（级联删除订阅）"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(f"""
            DELETE FROM user_sessions
            WHERE last_active < datetime('now', '-{days} days')
        """)
        deleted_count = cursor.rowcount
        conn.commit()
        return deleted_count
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

# ============ 用户订阅管理 ============

def subscribe_channels(socket_id, channel_ids):
    """用户订阅频道"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        for channel_id in channel_ids:
            cursor.execute("""
                INSERT OR IGNORE INTO user_subscriptions (socket_id, channel_id)
                VALUES (?, ?)
            """, (socket_id, channel_id))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def unsubscribe_channels(socket_id, channel_ids):
    """用户取消订阅"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        for channel_id in channel_ids:
            cursor.execute("""
                DELETE FROM user_subscriptions
                WHERE socket_id = ? AND channel_id = ?
            """, (socket_id, channel_id))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def get_user_subscriptions(socket_id):
    """获取用户订阅列表"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT channel_id
        FROM user_subscriptions
        WHERE socket_id = ?
    """, (socket_id,))
    rows = cursor.fetchall()
    conn.close()
    return [row['channel_id'] for row in rows]

def set_current_channel(socket_id, channel_id):
    """设置用户当前频道"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE user_sessions
        SET current_channel = ?, last_active = CURRENT_TIMESTAMP
        WHERE socket_id = ?
    """, (channel_id, socket_id))
    conn.commit()
    conn.close()

def get_current_channel(socket_id):
    """获取用户当前频道"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT current_channel FROM user_sessions WHERE socket_id = ?", (socket_id,))
    row = cursor.fetchone()
    conn.close()
    return row['current_channel'] if row else None

# ============ 消息推送相关 ============

def get_subscribers_for_channel(channel_id):
    """获取订阅某频道的所有在线socket_id"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # 先获取订阅了该频道的用户ID列表（socket_id存储的是用户ID）
    cursor.execute("""
        SELECT socket_id
        FROM user_subscriptions
        WHERE channel_id = ?
    """, (channel_id,))
    subscribed_user_ids = [row['socket_id'] for row in cursor.fetchall()]

    # 查找这些用户当前在线的WebSocket连接
    if not subscribed_user_ids:
        conn.close()
        return []

    placeholders = ','.join(['?' for _ in subscribed_user_ids])
    cursor.execute(f"""
        SELECT socket_id
        FROM user_sessions
        WHERE user_id IN ({placeholders})
        AND last_active > datetime('now', '-5 minutes')
    """, subscribed_user_ids)

    rows = cursor.fetchall()
    conn.close()
    return [row['socket_id'] for row in rows]

def get_all_active_sessions():
    """获取所有活跃会话"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT socket_id, current_channel
        FROM user_sessions
        WHERE last_active > datetime('now', '-5 minutes')
    """)
    rows = cursor.fetchall()
    conn.close()
    return [{'socket_id': row['socket_id'], 'current_channel': row['current_channel']} for row in rows]

# ============ 未读消息管理（大厂设计方案）============

def get_unread_count(user_id, channel_id):
    """获取某频道未读消息数（基于已读游标）"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # 获取该用户在该频道的已读游标
    cursor.execute("""
        SELECT last_read_message_id
        FROM user_read_cursors
        WHERE user_id = ? AND channel_id = ?
    """, (user_id, channel_id))
    row = cursor.fetchone()

    if not row:
        # 没有游标记录，返回0
        conn.close()
        return 0

    last_read_id = row['last_read_message_id']

    # 计算未读数：该频道总消息数 - 已读消息ID
    cursor.execute("""
        SELECT COUNT(*) as count
        FROM messages
        WHERE channel_id = ? AND id > ?
    """, (channel_id, last_read_id))

    unread_count = cursor.fetchone()['count']
    conn.close()
    return unread_count

def mark_messages_as_read(user_id, channel_id):
    """标记该频道的所有消息为已读（更新游标到最新消息）"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # 获取该频道最新的消息ID
    cursor.execute("""
        SELECT MAX(id) as max_id
        FROM messages
        WHERE channel_id = ?
    """, (channel_id,))
    row = cursor.fetchone()

    latest_message_id = row['max_id'] if row and row['max_id'] else 0

    # 更新或插入已读游标
    cursor.execute("""
        INSERT INTO user_read_cursors (user_id, channel_id, last_read_message_id, updated_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id, channel_id)
        DO UPDATE SET
            last_read_message_id = ?,
            updated_at = CURRENT_TIMESTAMP
    """, (user_id, channel_id, latest_message_id, latest_message_id))

    conn.commit()
    conn.close()

def get_all_unread_counts(user_id):
    """获取用户所有频道的未读数（批量查询，优化性能）"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # 获取用户所有频道的已读游标
    cursor.execute("""
        SELECT channel_id, last_read_message_id
        FROM user_read_cursors
        WHERE user_id = ?
    """, (user_id,))
    cursors = {row['channel_id']: row['last_read_message_id'] for row in cursor.fetchall()}

    # 获取每个频道的未读数
    unread_counts = {}
    for channel_id, last_read_id in cursors.items():
        cursor.execute("""
            SELECT COUNT(*) as count
            FROM messages
            WHERE channel_id = ? AND id > ?
        """, (channel_id, last_read_id))
        unread_counts[channel_id] = cursor.fetchone()['count']

    conn.close()
    return unread_counts

# ============ 标签管理 ============

def get_all_categories(category_type='public'):
    """获取所有标签（按频率降序）

    Args:
        category_type: 标签类型，'public' 或 'private'
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, name, frequency, type FROM categories WHERE type = ? ORDER BY frequency DESC",
        (category_type,)
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_category(category_id):
    """获取单个标签"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM categories WHERE id = ?", (category_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def create_category(name, frequency=50, category_type='public'):
    """创建标签

    Args:
        name: 标签名称
        frequency: 频率 (0-100)
        category_type: 标签类型，'public' 或 'private'
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO categories (name, frequency, type)
            VALUES (?, ?, ?)
        """, (name, frequency, category_type))
        conn.commit()
        return cursor.lastrowid  # 返回新创建的ID
    except Exception as e:
        logger.error(f"创建标签失败: {e}")
        return None
    finally:
        conn.close()

def update_category(category_id, name=None, frequency=None):
    """更新标签"""
    conn = get_db_connection()
    cursor = conn.cursor()

    updates = []
    params = []

    if name is not None:
        updates.append("name = ?")
        params.append(name)
    if frequency is not None:
        updates.append("frequency = ?")
        params.append(frequency)

    if not updates:
        conn.close()
        return False

    params.append(category_id)
    query = f"UPDATE categories SET {', '.join(updates)} WHERE id = ?"

    cursor.execute(query, params)
    conn.commit()
    affected = cursor.rowcount
    conn.close()
    return affected > 0

def delete_category(category_id):
    """删除标签"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM categories WHERE id = ?", (category_id,))
    conn.commit()
    affected = cursor.rowcount
    conn.close()
    return affected > 0

# ============ 用户管理 ============

def create_user(email, password, nickname, is_admin=0, is_active=1):
    """创建用户"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO users (email, password, nickname, is_admin, is_active)
            VALUES (?, ?, ?, ?, ?)
        """, (email, password, nickname, is_admin, is_active))
        conn.commit()
        return cursor.lastrowid
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()

def get_user_by_email(email):
    """根据邮箱获取用户"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_user_by_id(user_id):
    """根据ID获取用户"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def update_user(user_id, email=None, password=None, nickname=None, is_admin=None, is_active=None):
    """更新用户信息"""
    conn = get_db_connection()
    cursor = conn.cursor()

    updates = []
    params = []

    if email is not None:
        updates.append("email = ?")
        params.append(email)
    if password is not None:
        updates.append("password = ?")
        params.append(password)
    if nickname is not None:
        updates.append("nickname = ?")
        params.append(nickname)
    if is_admin is not None:
        updates.append("is_admin = ?")
        params.append(is_admin)
    if is_active is not None:
        updates.append("is_active = ?")
        params.append(is_active)

    if not updates:
        conn.close()
        return False

    params.append(user_id)

    query = f"UPDATE users SET {', '.join(updates)} WHERE id = ?"
    cursor.execute(query, params)
    conn.commit()
    affected = cursor.rowcount
    conn.close()
    return affected > 0

def delete_user(user_id):
    """删除用户"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    affected = cursor.rowcount
    conn.close()
    return affected > 0

def get_all_users(limit=50, offset=0, search=''):
    """获取用户列表（支持分页和搜索）"""
    conn = get_db_connection()
    cursor = conn.cursor()

    if search:
        # 搜索邮箱或昵称
        cursor.execute("""
            SELECT id, email, password, nickname, is_admin, is_active, created_at
            FROM users
            WHERE email LIKE ? OR nickname LIKE ?
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """, (f'%{search}%', f'%{search}%', limit, offset))
    else:
        cursor.execute("""
            SELECT id, email, password, nickname, is_admin, is_active, created_at
            FROM users
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """, (limit, offset))

    rows = cursor.fetchall()

    # 获取总数
    if search:
        cursor.execute("""
            SELECT COUNT(*) as total
            FROM users
            WHERE email LIKE ? OR nickname LIKE ?
        """, (f'%{search}%', f'%{search}%'))
    else:
        cursor.execute("SELECT COUNT(*) as total FROM users")

    total = cursor.fetchone()['total']
    conn.close()

    return {
        'users': [dict(row) for row in rows],
        'total': total,
        'limit': limit,
        'offset': offset
    }

def save_user_token(user_id, token, expires_at):
    """保存用户token"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO user_tokens (user_id, token, expires_at)
            VALUES (?, ?, ?)
        """, (user_id, token, expires_at))
        conn.commit()
        return True
    except:
        return False
    finally:
        conn.close()

def get_user_by_token(token):
    """根据token获取用户"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT u.* FROM users u
        INNER JOIN user_tokens t ON u.id = t.user_id
        WHERE t.token = ? AND t.expires_at > datetime('now')
    """, (token,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def delete_user_token(token):
    """删除用户token"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM user_tokens WHERE token = ?", (token,))
    conn.commit()
    conn.close()

def cleanup_expired_tokens():
    """清理过期token"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM user_tokens WHERE expires_at <= datetime('now')")
    deleted_count = cursor.rowcount
    conn.commit()
    conn.close()
    return deleted_count

# ============ 验证码管理 ============

def save_verification_code(email, code, code_type='register', expire_minutes=5):
    """保存验证码"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # 计算过期时间
    from datetime import datetime, timedelta
    expires_at = (datetime.now() + timedelta(minutes=expire_minutes)).strftime('%Y-%m-%d %H:%M:%S')

    try:
        cursor.execute("""
            INSERT INTO verification_codes (email, code, type, expires_at)
            VALUES (?, ?, ?, ?)
        """, (email, code, code_type, expires_at))
        conn.commit()
        return True
    except:
        return False
    finally:
        conn.close()

def verify_code(email, code, code_type='register'):
    """验证验证码"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # 查找未使用的有效验证码
    cursor.execute("""
        SELECT id FROM verification_codes
        WHERE email = ? AND code = ? AND type = ?
        AND expires_at > datetime('now')
        AND used = 0
        ORDER BY created_at DESC
        LIMIT 1
    """, (email, code, code_type))

    row = cursor.fetchone()

    if row:
        # 标记为已使用
        cursor.execute("UPDATE verification_codes SET used = 1 WHERE id = ?", (row['id'],))
        conn.commit()
        conn.close()
        return True
    else:
        conn.close()
        return False

def check_code_send_limit(email, code_type='register', limit_seconds=60):
    """检查验证码发送频率限制"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # 查找最近一次发送的验证码
    cursor.execute("""
        SELECT created_at FROM verification_codes
        WHERE email = ? AND type = ?
        ORDER BY created_at DESC
        LIMIT 1
    """, (email, code_type))

    row = cursor.fetchone()
    conn.close()

    if not row:
        return True  # 没有发送过，允许发送

    # 检查时间间隔
    from datetime import datetime
    last_sent = datetime.strptime(row['created_at'], '%Y-%m-%d %H:%M:%S')
    elapsed = (datetime.now() - last_sent).total_seconds()

    return elapsed >= limit_seconds

def cleanup_expired_codes():
    """清理过期验证码"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM verification_codes WHERE expires_at <= datetime('now')")
    deleted_count = cursor.rowcount
    conn.commit()
    conn.close()
    return deleted_count

def get_channels_latest_message_time(channel_ids=None):
    """批量获取频道的最新消息时间

    Args:
        channel_ids: 频道ID列表，如果为None则查询所有频道

    Returns:
        dict: {channel_id: latest_timestamp} 格式的字典
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    if channel_ids:
        # 查询指定频道
        placeholders = ','.join(['?' for _ in channel_ids])
        query = f"""
            SELECT channel_id, MAX(timestamp) as latest_time
            FROM messages
            WHERE channel_id IN ({placeholders})
            GROUP BY channel_id
        """
        cursor.execute(query, channel_ids)
    else:
        # 查询所有频道
        cursor.execute("""
            SELECT channel_id, MAX(timestamp) as latest_time
            FROM messages
            GROUP BY channel_id
        """)

    result = {row['channel_id']: row['latest_time'] for row in cursor.fetchall()}
    conn.close()
    return result

# ============ 卡密管理 ============

def init_card_tables():
    """初始化卡密相关表"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # 创建卡密模板表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS card_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            channel_pool TEXT NOT NULL,
            max_channels INTEGER NOT NULL,
            validity_days INTEGER NOT NULL,
            category_filter TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 创建卡密表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS card_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE,
            template_id INTEGER NOT NULL,
            template_name TEXT NOT NULL,
            is_activated INTEGER DEFAULT 0,
            activated_at TIMESTAMP,
            expires_at TIMESTAMP,
            bound_user_id INTEGER,
            bound_account TEXT,
            selected_channels TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (template_id) REFERENCES card_templates(id),
            FOREIGN KEY (bound_user_id) REFERENCES users(id)
        )
    ''')

    conn.commit()
    conn.close()
    print('✓ 卡密表初始化完成')

def get_all_templates():
    """获取所有卡密模板"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM card_templates ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_template_by_id(template_id):
    """根据ID获取模板"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM card_templates WHERE id = ?", (template_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def create_template(name, channel_pool, max_channels, validity_days, category_filter=None):
    """创建卡密模板"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO card_templates (name, channel_pool, max_channels, validity_days, category_filter)
        VALUES (?, ?, ?, ?, ?)
    ''', (name, json.dumps(channel_pool), max_channels, validity_days,
          json.dumps(category_filter) if category_filter else None))
    template_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return template_id

def update_template(template_id, name=None, channel_pool=None, max_channels=None, validity_days=None, category_filter=None, is_active=None):
    """更新卡密模板"""
    conn = get_db_connection()
    cursor = conn.cursor()

    updates = []
    params = []

    if name is not None:
        updates.append("name = ?")
        params.append(name)
    if channel_pool is not None:
        updates.append("channel_pool = ?")
        params.append(json.dumps(channel_pool))
    if max_channels is not None:
        updates.append("max_channels = ?")
        params.append(max_channels)
    if validity_days is not None:
        updates.append("validity_days = ?")
        params.append(validity_days)
    if category_filter is not None:
        updates.append("category_filter = ?")
        params.append(json.dumps(category_filter) if category_filter else None)
    if is_active is not None:
        updates.append("is_active = ?")
        params.append(is_active)

    updates.append("updated_at = CURRENT_TIMESTAMP")
    params.append(template_id)

    cursor.execute(f"UPDATE card_templates SET {', '.join(updates)} WHERE id = ?", params)
    conn.commit()
    conn.close()
    return True

def delete_template(template_id):
    """删除卡密模板"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM card_templates WHERE id = ?", (template_id,))
    conn.commit()
    conn.close()
    return True

def get_card_by_code(code):
    """根据卡密字符串获取卡密"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM card_codes WHERE code = ?", (code,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_card_by_id(card_id):
    """根据ID获取卡密"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM card_codes WHERE id = ?", (card_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_all_cards(page=1, per_page=20, template_id=None, is_activated=None, search=None):
    """获取卡密列表（分页）"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # 构建查询条件
    conditions = []
    params = []

    if template_id:
        conditions.append("template_id = ?")
        params.append(template_id)
    if is_activated is not None:
        conditions.append("is_activated = ?")
        params.append(is_activated)
    if search:
        conditions.append("(code LIKE ? OR bound_account LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    # 获取总数
    cursor.execute(f"SELECT COUNT(*) as total FROM card_codes {where_clause}", params)
    total = cursor.fetchone()['total']

    # 分页查询
    offset = (page - 1) * per_page
    params.extend([per_page, offset])
    cursor.execute(f"""
        SELECT * FROM card_codes
        {where_clause}
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
    """, params)

    rows = cursor.fetchall()
    conn.close()

    return {
        'cards': [dict(row) for row in rows],
        'total': total,
        'page': page,
        'per_page': per_page,
        'pages': (total + per_page - 1) // per_page
    }

def generate_cards(template_id, count):
    """批量生成卡密"""
    import secrets
    from datetime import datetime

    template = get_template_by_id(template_id)
    if not template:
        return None

    conn = get_db_connection()
    cursor = conn.cursor()

    cards = []
    for _ in range(count):
        # 生成唯一卡密
        while True:
            code = f"CARD-{secrets.token_urlsafe(16).upper()}"
            try:
                cursor.execute("INSERT INTO card_codes (code, template_id, template_name) VALUES (?, ?, ?)",
                             (code, template_id, template['name']))
                break
            except sqlite3.IntegrityError:
                continue  # 卡密重复，重新生成

        card_id = cursor.lastrowid
        cards.append({
            'id': card_id,
            'code': code,
            'template_id': template_id,
            'template_name': template['name']
        })

    conn.commit()
    conn.close()
    return cards

def delete_card(card_id):
    """删除卡密"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM card_codes WHERE id = ?", (card_id,))
    conn.commit()
    conn.close()
    return True

def update_card_activation(card_id, is_activated=None, activated_at=None, expires_at=None,
                          bound_user_id=None, bound_account=None, selected_channels=None):
    """更新卡密激活状态"""
    conn = get_db_connection()
    cursor = conn.cursor()

    updates = []
    params = []

    if is_activated is not None:
        updates.append("is_activated = ?")
        params.append(is_activated)
    if activated_at is not None:
        updates.append("activated_at = ?")
        params.append(activated_at)
    if expires_at is not None:
        updates.append("expires_at = ?")
        params.append(expires_at)
    if bound_user_id is not None:
        updates.append("bound_user_id = ?")
        params.append(bound_user_id)
    if bound_account is not None:
        updates.append("bound_account = ?")
        params.append(bound_account)
    if selected_channels is not None:
        updates.append("selected_channels = ?")
        params.append(json.dumps(selected_channels))

    updates.append("updated_at = CURRENT_TIMESTAMP")
    params.append(card_id)

    cursor.execute(f"UPDATE card_codes SET {', '.join(updates)} WHERE id = ?", params)
    conn.commit()
    conn.close()
    return True

def get_user_cards(user_id):
    """获取用户的卡密列表"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM card_codes
        WHERE bound_user_id = ?
        ORDER BY activated_at DESC
    """, (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

# ============ 推送设置管理 ============

def get_push_settings():
    """获取推送设置"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM push_settings ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    conn.close()

    if row:
        settings = dict(row)
        # 解析JSON字段
        if settings.get('switch_times'):
            try:
                settings['switch_times'] = json.loads(settings['switch_times'])
            except:
                settings['switch_times'] = []
        else:
            settings['switch_times'] = []
        # 切换缓冲时间（秒）
        settings['switch_buffer_seconds'] = settings.get('switch_buffer_seconds') or 0
        return settings
    else:
        return {
            'mode': 'all',
            'switch_times': [],
            'interval_minutes': None,
            'active_token_index': 0,
            'roundrobin_indices': '{}',
            'switch_buffer_seconds': 0
        }

def update_push_settings(mode, switch_times=None, interval_minutes=None):
    """更新推送设置

    Args:
        mode: all 或 roundrobin
        switch_times: 时间点列表，如 ["08:00", "14:00", "20:00"]
        interval_minutes: 间隔分钟数
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # 先删除旧设置
    cursor.execute("DELETE FROM push_settings")

    # 插入新设置
    switch_times_json = json.dumps(switch_times) if switch_times else None
    cursor.execute("""
        INSERT INTO push_settings (mode, switch_times, interval_minutes, active_token_index)
        VALUES (?, ?, ?, 0)
    """, (mode, switch_times_json, interval_minutes))

    conn.commit()
    conn.close()
    return True

# 缓存当前活跃令牌列表（由定时任务维护）
_active_tokens_cache = None
_active_tokens_set = None  # 用于O(1)快速查找

def get_active_tokens_for_push():
    """获取当前活跃的推送令牌（从缓存读取，不查数据库）"""
    global _active_tokens_cache, _active_tokens_set

    if _active_tokens_cache is None:
        # 首次调用，查询初始化
        settings = get_push_settings()

        if settings['mode'] != 'roundrobin':
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT ct.id, ct.token, ct.channel_id, c.name as channel_name
                FROM channel_tokens ct
                JOIN channels c ON ct.channel_id = c.id
                ORDER BY ct.id
            """)
            rows = cursor.fetchall()
            conn.close()
            result = [dict(row) for row in rows]
        else:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                WITH ranked_tokens AS (
                    SELECT
                        ct.id, ct.token, ct.channel_id, c.name as channel_name,
                        ROW_NUMBER() OVER (PARTITION BY ct.channel_id ORDER BY ct.id) - 1 as token_rank
                    FROM channel_tokens ct
                    JOIN channels c ON ct.channel_id = c.id
                ),
                token_counts AS (
                    SELECT channel_id, COUNT(*) as total
                    FROM channel_tokens
                    GROUP BY channel_id
                )
                SELECT rt.id, rt.token, rt.channel_id, rt.channel_name
                FROM ranked_tokens rt
                JOIN token_counts tc ON rt.channel_id = tc.channel_id
                WHERE rt.token_rank = (
                    SELECT COALESCE(json_extract(roundrobin_indices, '$.' || rt.channel_id), 0) % tc.total
                    FROM push_settings
                )
                ORDER BY rt.channel_id
            """)
            rows = cursor.fetchall()
            conn.close()
            result = [dict(row) for row in rows]

        _active_tokens_cache = result
        _active_tokens_set = {t['token'] for t in result}

    return _active_tokens_cache

def is_token_active(token):
    """快速检查令牌是否活跃（O(1)查找）"""
    global _active_tokens_set
    if _active_tokens_set is None:
        # 首次调用，初始化缓存
        get_active_tokens_for_push()
    return token in _active_tokens_set

def switch_active_token():
    """切换到下一个活跃令牌（轮询模式）- 每个频道独立切换 + 更新缓存"""
    global _active_tokens_cache, _active_tokens_set

    conn = get_db_connection()
    cursor = conn.cursor()

    # 获取所有频道的令牌数量
    cursor.execute("""
        SELECT channel_id, COUNT(*) as total_tokens
        FROM channel_tokens
        GROUP BY channel_id
    """)
    channel_token_counts = {row['channel_id']: row['total_tokens'] for row in cursor.fetchall()}

    # 获取当前索引
    cursor.execute("SELECT roundrobin_indices FROM push_settings LIMIT 1")
    result = cursor.fetchone()
    import json
    indices = {}
    if result and result['roundrobin_indices']:
        try:
            indices = json.loads(result['roundrobin_indices'])
        except:
            indices = {}

    # 每个频道的索引前进1
    for channel_id, count in channel_token_counts.items():
        current_index = indices.get(channel_id, 0)
        next_index = (current_index + 1) % count
        indices[channel_id] = next_index

    # 先更新数据库
    cursor.execute("UPDATE push_settings SET roundrobin_indices = ?", (json.dumps(indices),))
    conn.commit()
    conn.close()

    # 再更新缓存（查询新令牌，更新缓存）
    # 这样推送请求只读缓存，不查数据库
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        WITH ranked_tokens AS (
            SELECT
                ct.id, ct.token, ct.channel_id, c.name as channel_name,
                ROW_NUMBER() OVER (PARTITION BY ct.channel_id ORDER BY ct.id) - 1 as token_rank
            FROM channel_tokens ct
            JOIN channels c ON ct.channel_id = c.id
        ),
        token_counts AS (
            SELECT channel_id, COUNT(*) as total
            FROM channel_tokens
            GROUP BY channel_id
        )
        SELECT rt.id, rt.token, rt.channel_id, rt.channel_name
        FROM ranked_tokens rt
        JOIN token_counts tc ON rt.channel_id = tc.channel_id
        WHERE rt.token_rank = (
            SELECT COALESCE(json_extract(roundrobin_indices, '$.' || rt.channel_id), 0) % tc.total
            FROM push_settings
        )
        ORDER BY rt.channel_id
    """)
    rows = cursor.fetchall()
    conn.close()
    result = [dict(row) for row in rows]

    # 更新全局缓存
    _active_tokens_cache = result
    _active_tokens_set = {t['token'] for t in result}

    return indices

def get_messages_list(page=1, per_page=20, channel_id='', channel_type='', category_id='', token='', is_filtered=None, search_content=''):
    """获取消息列表（支持筛选、搜索、分页）

    Args:
        page: 页码
        per_page: 每页数量
        channel_id: 频道ID筛选
        channel_type: 频道类型筛选
        category_id: 标签ID筛选
        token: 令牌筛选
        is_filtered: 是否过滤筛选 (True/False/None)
        search_content: 搜索消息标题或内容

    Returns:
        dict: {
            'messages': [],  # 消息列表
            'total': 0,      # 总数
            'page': 1,       # 当前页
            'per_page': 20,  # 每页数量
            'total_pages': 1 # 总页数
        }
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # 构建查询条件
    where_conditions = []
    params = []

    # 基础JOIN和查询
    query = """
        SELECT
            m.id, m.channel_id, m.content, m.token, m.timestamp, m.doubao_ai,
            c.name as channel_name, c.type as channel_type, c.category_id,
            cat.name as category_name
        FROM messages m
        LEFT JOIN channels c ON m.channel_id = c.id
        LEFT JOIN categories cat ON c.category_id = cat.id
        WHERE 1=1
    """

    # 频道筛选
    if channel_id:
        where_conditions.append("m.channel_id = ?")
        params.append(channel_id)

    # 类型筛选
    if channel_type:
        where_conditions.append("c.type = ?")
        params.append(channel_type)

    # 标签筛选
    if category_id:
        where_conditions.append("c.category_id = ?")
        params.append(category_id)

    # 令牌筛选
    if token:
        where_conditions.append("m.token = ?")
        params.append(token)

    # 消息内容搜索
    if search_content:
        where_conditions.append("(m.content LIKE ? OR m.title LIKE ?)")
        params.extend([f'%{search_content}%', f'%{search_content}%'])

    # 组合WHERE条件
    if where_conditions:
        query += " AND " + " AND ".join(where_conditions)

    # 获取总数
    count_query = f"SELECT COUNT(*) as count FROM ({query}) as subquery"
    cursor.execute(count_query, params)
    total = cursor.fetchone()['count']

    # 排序和分页
    query += " ORDER BY m.id DESC LIMIT ? OFFSET ?"
    offset = (page - 1) * per_page
    params.extend([per_page, offset])

    # 执行查询
    cursor.execute(query, params)
    rows = cursor.fetchall()

    # 获取推送设置和活跃令牌（用于判断是否被过滤）
    push_settings = get_push_settings()
    active_tokens = []
    if push_settings['mode'] == 'roundrobin':
        active_tokens = get_active_tokens_for_push()
        active_tokens_list = [t['token'] for t in active_tokens]

    # 处理结果
    messages = []
    for row in rows:
        message = dict(row)

        # 判断是否被过滤
        if push_settings['mode'] == 'roundrobin':
            message['is_filtered'] = message['token'] not in active_tokens_list
        else:
            message['is_filtered'] = False

        # 应用过滤状态筛选
        if is_filtered is not None:
            if is_filtered and not message['is_filtered']:
                continue
            if not is_filtered and message['is_filtered']:
                continue

        # 添加频道名称用于显示
        message['channel_display'] = f"{message['channel_name']} (ID: {message['channel_id']})"

        messages.append(message)

    conn.close()

    # 计算总页数（重新计算，考虑了过滤）
    total_after_filter = len(messages)

    return {
        'messages': messages,
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': (total + per_page - 1) // per_page
    }

# 启动时初始化数据库
if __name__ == '__main__':
    init_database()
