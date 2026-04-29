"""
配置管理模块
从 config.json 加载配置，提供统一的配置访问接口
"""
import json
import os
from pathlib import Path

# 配置文件路径
CONFIG_FILE = os.path.join(os.path.dirname(__file__), '..', 'config.json')

class Config:
    """配置类"""

    def __init__(self, config_file=CONFIG_FILE):
        """初始化配置"""
        self.config_file = config_file
        self.load_config()

    def load_config(self):
        """加载配置文件"""
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
                self.config = config
        except FileNotFoundError:
            print(f"警告: 配置文件 {self.config_file} 不存在，使用默认配置")
            self.config = self.get_default_config()
        except json.JSONDecodeError as e:
            print(f"错误: 配置文件格式不正确: {e}")
            self.config = self.get_default_config()

    def get_default_config(self):
        """获取默认配置"""
        return {
            "server": {
                "host": "0.0.0.0",
                "public_ip": "localhost",
                "domain": ""
            },
            "ports": {
                "flask_backend": 5555,
                "websocket_server": 9080,
                "frontend": 8000
            },
            "urls": {
                "flask_backend": "http://localhost:5555",
                "websocket_server": "ws://localhost:9080",
                "frontend": "http://localhost:8000",
                "push_api": "http://localhost:5555/push/send"
            },
            "admin": {
                "token": "724caixun_admin_2024_k9HxM7qL",
                "url": "http://localhost:8000/admin.html"
            },
            "websocket": {
                "flask_to_ws": "http://localhost:9080",
                "ws_to_flask": "http://localhost:5555"
            }
        }

    def get(self, key_path, default=None):
        """
        获取配置值

        Args:
            key_path: 配置路径，如 'server.host' 或 'ports.flask_backend'
            default: 默认值

        Returns:
            配置值或默认值
        """
        keys = key_path.split('.')
        value = self.config

        try:
            for key in keys:
                value = value[key]
            return value
        except (KeyError, TypeError):
            return default

    @property
    def FLASK_HOST(self):
        """Flask服务主机"""
        return self.get('server.host', '0.0.0.0')

    @property
    def FLASK_PORT(self):
        """Flask服务端口"""
        return self.get('ports.flask_backend', 5555)

    @property
    def WEBSOCKET_PORT(self):
        """WebSocket服务端口"""
        return self.get('ports.websocket_server', 9080)

    @property
    def FRONTEND_PORT(self):
        """前端服务端口"""
        return self.get('ports.frontend', 8000)

    @property
    def PUBLIC_IP(self):
        """公网IP"""
        return self.get('server.public_ip', 'localhost')

    @property
    def FLASK_URL(self):
        """Flask服务URL"""
        return self.get('urls.flask_backend', f'http://{self.PUBLIC_IP}:{self.FLASK_PORT}')

    @property
    def WEBSOCKET_URL(self):
        """WebSocket服务URL"""
        return self.get('urls.websocket_server', f'ws://{self.PUBLIC_IP}:{self.WEBSOCKET_PORT}')

    @property
    def FRONTEND_URL(self):
        """前端服务URL"""
        return self.get('urls.frontend', f'http://{self.PUBLIC_IP}:{self.FRONTEND_PORT}')

    @property
    def PUSH_API_URL(self):
        """推送API URL"""
        return self.get('urls.push_api', f'{self.FLASK_URL}/push/send')

    @property
    def PUSH_SERVICE_URL(self):
        """推送服务URL（Flask内部调用WebSocket）"""
        return self.get('websocket.flask_to_ws', f'http://localhost:{self.WEBSOCKET_PORT}')

    @property
    def ADMIN_TOKEN(self):
        """管理员Token"""
        return self.get('admin.token', '724caixun_admin_2024_k9HxM7qL')

    @property
    def ADMIN_URL(self):
        """管理员登录URL"""
        return self.get('admin.url', f'{self.FRONTEND_URL}/admin.html')

    @property
    def AI_PROVIDER(self):
        """当前使用的AI提供商"""
        return self.get('ai_provider', 'doubao')

    def update_ai_provider(self, provider):
        """
        更新当前AI提供商

        Args:
            provider: AI提供商 (doubao/siliconflow)
        """
        if provider not in ['doubao', 'siliconflow']:
            raise ValueError('Invalid provider, must be "doubao" or "siliconflow"')

        self.config['ai_provider'] = provider

        # 写入文件
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"写入配置文件失败: {e}")
            return False

    @property
    def DOUBAO_API_KEY(self):
        """豆包API Key"""
        return self.get('doubao.api_key', '')

    @property
    def DOUBAO_API_URL(self):
        """豆包API URL"""
        return self.get('doubao.api_url', 'https://ark.cn-beijing.volces.com/api/v3/responses')

    @property
    def DOUBAO_MODEL(self):
        """豆包模型名称"""
        return self.get('doubao.model', 'doubao-seed-2-0-pro-260215')

    @property
    def DOUBAO_PROMPT(self):
        """豆包提示词"""
        return self.get('doubao.prompt', '')

    def update_doubao_config(self, api_key=None, api_url=None, model=None, prompt=None):
        """
        更新豆包配置到内存和文件

        Args:
            api_key: API密钥
            api_url: API地址
            model: 模型名称
            prompt: 提示词
        """
        # 更新内存配置
        if api_key is not None:
            self.config.setdefault('doubao', {})['api_key'] = api_key
        if api_url is not None:
            self.config.setdefault('doubao', {})['api_url'] = api_url
        if model is not None:
            self.config.setdefault('doubao', {})['model'] = model
        if prompt is not None:
            self.config.setdefault('doubao', {})['prompt'] = prompt

        # 写入文件
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"写入配置文件失败: {e}")
            return False

    @property
    def SILICONFLOW_API_KEY(self):
        """硅基流动API Key"""
        return self.get('siliconflow.api_key', '')

    @property
    def SILICONFLOW_API_URL(self):
        """硅基流动API URL"""
        return self.get('siliconflow.api_url', 'https://api.siliconflow.cn/v1/chat/completions')

    @property
    def SILICONFLOW_MODEL(self):
        """硅基流动模型名称"""
        return self.get('siliconflow.model', 'deepseek-ai/DeepSeek-V3')

    @property
    def SILICONFLOW_PROMPT(self):
        """硅基流动提示词"""
        return self.get('siliconflow.prompt', '')

    def update_siliconflow_config(self, api_key=None, api_url=None, model=None, prompt=None):
        """
        更新硅基流动配置到内存和文件

        Args:
            api_key: API密钥
            api_url: API地址
            model: 模型名称
            prompt: 提示词
        """
        # 更新内存配置
        if api_key is not None:
            self.config.setdefault('siliconflow', {})['api_key'] = api_key
        if api_url is not None:
            self.config.setdefault('siliconflow', {})['api_url'] = api_url
        if model is not None:
            self.config.setdefault('siliconflow', {})['model'] = model
        if prompt is not None:
            self.config.setdefault('siliconflow', {})['prompt'] = prompt

        # 写入文件
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"写入配置文件失败: {e}")
            return False

# 创建全局配置实例
config = Config()

# 导出常用配置
FLASK_HOST = config.FLASK_HOST
FLASK_PORT = config.FLASK_PORT
WEBSOCKET_PORT = config.WEBSOCKET_PORT
FRONTEND_PORT = config.FRONTEND_PORT
PUBLIC_IP = config.PUBLIC_IP
FLASK_URL = config.FLASK_URL
WEBSOCKET_URL = config.WEBSOCKET_URL
FRONTEND_URL = config.FRONTEND_URL
PUSH_API_URL = config.PUSH_API_URL
PUSH_SERVICE_URL = config.PUSH_SERVICE_URL
ADMIN_TOKEN = config.ADMIN_TOKEN
ADMIN_URL = config.ADMIN_URL

if __name__ == '__main__':
    # 测试配置
    print("配置测试:")
    print(f"Flask主机: {FLASK_HOST}")
    print(f"Flask端口: {FLASK_PORT}")
    print(f"Flask URL: {FLASK_URL}")
    print(f"WebSocket端口: {WEBSOCKET_PORT}")
    print(f"前端 URL: {FRONTEND_URL}")
    print(f"推送API: {PUSH_API_URL}")
