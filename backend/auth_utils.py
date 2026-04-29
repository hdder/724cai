"""
认证工具函数：加密、解密、JWT token生成
"""
import base64
import jwt
import datetime
import secrets
from functools import wraps

# JWT密钥（生产环境应该从环境变量读取）
JWT_SECRET = "724caixun-secret-key-change-in-production"
JWT_ALGORITHM = "HS256"

# Token过期时间
ACCESS_TOKEN_EXPIRE_HOURS = 2
REFRESH_TOKEN_EXPIRE_DAYS = 15


def simple_encrypt(password):
    """
    简单加密：Base64 + 字符反转
    后台可以解密查看
    """
    # 1. Base64编码
    encoded = base64.b64encode(password.encode()).decode()

    # 2. 字符反转（简单混淆）
    reversed_str = encoded[::-1]

    # 3. 添加固定前缀标识
    return f"ENC1:{reversed_str}"


def simple_decrypt(encrypted_password):
    """
    解密密码
    """
    try:
        # 1. 移除前缀
        if encrypted_password.startswith("ENC1:"):
            encrypted_password = encrypted_password[5:]

        # 2. 反转回来
        reversed_str = encrypted_password[::-1]

        # 3. Base64解码
        decoded = base64.b64decode(reversed_str).decode()

        return decoded
    except Exception as e:
        raise ValueError(f"密码解密失败: {str(e)}")


def generate_access_token(user_id):
    """
    生成访问token
    """
    payload = {
        'user_id': user_id,
        'type': 'access',
        'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS),
        'iat': datetime.datetime.utcnow()
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return token


def generate_refresh_token(user_id):
    """
    生成刷新token
    """
    payload = {
        'user_id': user_id,
        'type': 'refresh',
        'exp': datetime.datetime.utcnow() + datetime.timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
        'iat': datetime.datetime.utcnow()
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return token


def verify_token(token):
    """
    验证token并返回payload
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None  # Token过期
    except jwt.InvalidTokenError:
        return None  # Token无效


def require_auth(f):
    """
    装饰器：验证JWT token
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        from flask import request, jsonify

        auth_header = request.headers.get('Authorization')

        if not auth_header:
            return jsonify({'success': False, 'message': '缺少认证token'}), 401

        # Bearer token格式
        if auth_header.startswith('Bearer '):
            token = auth_header[7:]
        else:
            token = auth_header

        payload = verify_token(token)

        if not payload:
            return jsonify({'success': False, 'message': 'Token无效或已过期'}), 401

        # 将user_id存入request上下文
        request.user_id = payload['user_id']

        return f(*args, **kwargs)

    return decorated_function


def require_admin(f):
    """
    装饰器：验证管理员权限（支持 JWT token 或 admin_token 参数）
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        from flask import request, jsonify

        # 优先使用 admin_token 参数（兼容旧版管理后台）
        admin_token = request.args.get('admin_token')
        if admin_token and admin_token == '724caixun_admin_2024_k9HxM7qL':
            return f(*args, **kwargs)

        # 否则使用 JWT token
        auth_header = request.headers.get('Authorization')

        if not auth_header:
            return jsonify({'success': False, 'message': '缺少认证token'}), 401

        if auth_header.startswith('Bearer '):
            token = auth_header[7:]
        else:
            token = auth_header

        payload = verify_token(token)

        if not payload:
            return jsonify({'success': False, 'message': 'Token无效或已过期'}), 401

        # 检查是否是管理员
        from database import get_user_by_id
        user = get_user_by_id(payload['user_id'])

        if not user or not user.get('is_admin'):
            return jsonify({'success': False, 'message': '需要管理员权限'}), 403

        request.user_id = payload['user_id']

        return f(*args, **kwargs)

    return decorated_function


def generate_verification_code():
    """
    生成6位数字验证码
    """
    return str(secrets.randbelow(900000) + 100000)
