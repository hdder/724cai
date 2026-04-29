/**
 * 前端配置文件
 * 自动从后端配置API加载，或使用默认配置
 * 支持Vercel部署：通过环境变量或URL参数指定后端地址
 */

// 默认配置（开发环境）
const DEFAULT_CONFIG = {
    server: {
        host: 'localhost',
        public_ip: '111.228.8.17'
    },
    ports: {
        flask_backend: 5555,
        websocket_server: 9080,
        frontend: 8000
    },
    urls: {
        flask_backend: 'http://111.228.8.17:5555',
        websocket_server: 'ws://111.228.8.17:9080',
        frontend: 'http://111.228.8.17:8000'
    },
    admin: {
        token: '724caixun_admin_2024_k9HxM7qL'
    }
};

// 当前配置
let currentConfig = { ...DEFAULT_CONFIG };

/**
 * 从当前URL自动检测配置
 */
function autoDetectConfig() {
    const currentHost = window.location.hostname;
    const currentPort = window.location.port;

    // 判断环境优先级
    if (currentHost === 'localhost' || currentHost === '127.0.0.1') {
        // 1. 本地开发环境
        return {
            server: {
                host: 'localhost',
                public_ip: 'localhost'
            },
            ports: {
                flask_backend: 5555,
                websocket_server: 9080,
                frontend: parseInt(currentPort) || 8000
            },
            urls: {
                flask_backend: 'http://localhost:5555',
                websocket_server: 'ws://localhost:9080',
                frontend: `http://localhost:${currentPort || 8000}`
            },
            admin: {
                token: '724caixun_admin_2024_k9HxM7qL'
            }
        };
    } else if (currentHost === '111.228.8.17') {
        // 2. 国内服务器前端 - 前后端在同一服务器
        const protocol = window.location.protocol;
        const wsProtocol = protocol === 'https:' ? 'wss:' : 'ws:';

        return {
            server: {
                host: currentHost,
                public_ip: currentHost
            },
            ports: {
                flask_backend: 5555,
                websocket_server: 9080,
                frontend: parseInt(currentPort) || 8000
            },
            urls: {
                flask_backend: `${protocol}//${currentHost}:5555`,
                websocket_server: `${wsProtocol}//${currentHost}:9080`,
                frontend: `${protocol}//${currentHost}:${currentPort || 8000}`
            },
            admin: {
                token: '724caixun_admin_2024_k9HxM7qL'
            }
        };
    } else if (currentHost === '724-cx.vercel.app') {
        // 3. Vercel前端 - 通过cloudflared隧道访问国内后端
        return {
            server: {
                host: currentHost,
                public_ip: currentHost
            },
            ports: {
                flask_backend: 5555,
                websocket_server: 9080,
                frontend: 443
            },
            urls: {
                flask_backend: 'https://vertex-palace-ends-emails.trycloudflare.com',
                websocket_server: 'wss://vertex-palace-ends-emails.trycloudflare.com',
                frontend: 'https://724-cx.vercel.app'
            },
            admin: {
                token: '724caixun_admin_2024_k9HxM7qL'
            }
        };
    } else {
        // 4. 其他环境（Netlify等）
        const protocol = window.location.protocol;
        const backendUrl = getBackendUrlFromEnv() || 'http://111.228.8.17:5555';
        const wsUrl = backendUrl.replace(/^http/, 'ws');

        return {
            server: {
                host: currentHost,
                public_ip: currentHost
            },
            ports: {
                flask_backend: 5555,
                websocket_server: 9080,
                frontend: 443
            },
            urls: {
                flask_backend: backendUrl,
                websocket_server: wsUrl,
                frontend: `${protocol}//${currentHost}`
            },
            admin: {
                token: '724caixun_admin_2024_k9HxM7qL'
            }
        };
    }
}

/**
 * 从环境变量或meta标签获取后端URL
 * Vercel环境变量需要在构建时注入到HTML
 */
function getBackendUrlFromEnv() {
    // 方法1：从meta标签读取（需要在HTML中添加<meta name="backend-url" content="...">）
    const metaTag = document.querySelector('meta[name="backend-url"]');
    if (metaTag && metaTag.content) {
        return metaTag.content;
    }

    // 方法2：从全局变量读取（需要在HTML中添加<script>window.BACKEND_URL="..."</script>）
    if (window.BACKEND_URL) {
        return window.BACKEND_URL;
    }

    // 方法3：从localStorage读取
    const savedUrl = localStorage.getItem('backend_url');
    if (savedUrl) {
        return savedUrl;
    }

    return null;
}

/**
 * 初始化配置
 */
function initConfig() {
    // 尝试从URL参数获取配置
    const urlParams = new URLSearchParams(window.location.search);
    const configHost = urlParams.get('config_host');
    const configPort = urlParams.get('config_port');

    if (configHost || configPort) {
        // 使用URL参数指定的配置
        const host = configHost || '111.228.8.17';
        const flaskPort = 5555;
        const wsPort = 9080;
        const frontendPort = parseInt(configPort) || 8000;

        currentConfig = {
            server: {
                host: host,
                public_ip: host
            },
            ports: {
                flask_backend: flaskPort,
                websocket_server: wsPort,
                frontend: frontendPort
            },
            urls: {
                flask_backend: `http://${host}:${flaskPort}`,
                websocket_server: `ws://${host}:${wsPort}`,
                frontend: `http://${host}:${frontendPort}`
            },
            admin: {
                token: '724caixun_admin_2024_k9HxM7qL'
            }
        };
    } else {
        // 自动检测配置
        currentConfig = autoDetectConfig();
    }

    return currentConfig;
}

/**
 * 获取配置值
 */
function getConfig(key) {
    const keys = key.split('.');
    let value = currentConfig;

    for (const k of keys) {
        if (value && typeof value === 'object') {
            value = value[k];
        } else {
            return null;
        }
    }

    return value;
}

/**
 * 获取API基础URL
 */
function getApiBase() {
    return currentConfig.urls.flask_backend;
}

/**
 * 获取WebSocket URL
 */
function getWebSocketUrl() {
    return currentConfig.urls.websocket_server;
}

/**
 * 获取前端URL
 */
function getFrontendUrl() {
    return currentConfig.urls.frontend;
}

/**
 * 获取管理员Token
 */
function getAdminToken() {
    return currentConfig.admin.token;
}

// 初始化配置
initConfig();

// 导出到全局
window.CONFIG = currentConfig;
window.getApiBase = getApiBase;
window.getWebSocketUrl = getWebSocketUrl;
window.getFrontendUrl = getFrontendUrl;
window.getAdminToken = getAdminToken;
