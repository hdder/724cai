/**
 * WebSocket服务器配置
 * 从根目录的config.json读取配置
 */
const fs = require('fs');
const path = require('path');

// 配置文件路径
const CONFIG_FILE = path.join(__dirname, '..', 'config.json');

// 默认配置
const DEFAULT_CONFIG = {
    ports: {
        flask_backend: 5555,
        websocket_server: 9080,
        frontend: 8000
    },
    server: {
        host: '0.0.0.0'
    }
};

// 加载配置
let config = DEFAULT_CONFIG;

try {
    if (fs.existsSync(CONFIG_FILE)) {
        const configContent = fs.readFileSync(CONFIG_FILE, 'utf8');
        config = JSON.parse(configContent);
        console.log('✓ 配置文件加载成功');
    } else {
        console.log('⚠ 配置文件不存在，使用默认配置');
    }
} catch (error) {
    console.error('✗ 配置文件加载失败:', error.message);
    console.log('使用默认配置');
}

// 导出配置
module.exports = {
    // 服务器端口
    WEBSOCKET_PORT: config.ports?.websocket_server || 9080,
    FLASK_PORT: config.ports?.flask_backend || 5555,

    // 服务器地址
    HOST: config.server?.host || '0.0.0.0',

    // Flask后端URL（WebSocket内部调用）
    FLASK_URL: `http://localhost:${config.ports?.flask_backend || 5555}`,

    // 完整配置
    config: config
};
