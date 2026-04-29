/**
 * 认证相关API
 */

const API_BASE = (() => {
    if (window.getApiBase) {
        return window.getApiBase() + '/api';
    }
    return `${window.location.protocol}//${window.location.hostname}:5555/api`;
})();

/**
 * 简单加密函数（用于传输）
 * 使用 Base64 + 字符反转 + 简单异或混淆
 * @param {string} text - 明文
 * @returns {string} 密文
 */
function encryptPassword(text) {
    // 1. 字符串反转
    let reversed = text.split('').reverse().join('');

    // 2. 对每个字符的 ASCII 码加上固定偏移量
    let shifted = '';
    for (let i = 0; i < reversed.length; i++) {
        shifted += String.fromCharCode(reversed.charCodeAt(i) + 3);
    }

    // 3. Base64 编码
    return btoa(shifted);
}

/**
 * 发送验证码
 */
async function sendVerificationCode(email, type = 'register', captcha = null, captchaKey = null) {
    const requestBody = { email, type };

    // Add captcha if provided
    if (captcha && captchaKey) {
        requestBody.captcha = captcha;
        requestBody.captcha_key = captchaKey;
    }

    const response = await fetch(`${API_BASE}/auth/send-code`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(requestBody)
    });
    return await response.json();
}

/**
 * 注册
 */
async function register(email, code, nickname, password) {
    // 加密密码用于传输
    const encryptedPassword = encryptPassword(password);

    const response = await fetch(`${API_BASE}/auth/register`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            email,
            code,
            nickname,
            password: encryptedPassword,
            encrypted: true  // 标记密码已加密
        })
    });
    return await response.json();
}

/**
 * 登录
 */
async function login(email, password) {
    // 加密密码用于传输
    const encryptedPassword = encryptPassword(password);

    const response = await fetch(`${API_BASE}/auth/login`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            email,
            password: encryptedPassword,
            encrypted: true  // 标记密码已加密
        })
    });
    return await response.json();
}

/**
 * 登出
 */
async function logout() {
    const token = localStorage.getItem('token');
    if (!token) {
        window.location.href = 'auth.html';
        return;
    }

    try {
        await fetch(`${API_BASE}/auth/logout`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            }
        });
    } catch (error) {
        console.error('登出失败:', error);
    } finally {
        localStorage.removeItem('token');
        localStorage.removeItem('user');
        window.location.href = 'auth.html';
    }
}

/**
 * 获取当前用户信息
 */
async function getCurrentUser() {
    const token = localStorage.getItem('token');
    if (!token) {
        return null;
    }

    const response = await fetch(`${API_BASE}/auth/me`, {
        method: 'GET',
        headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
        }
    });

    if (response.status === 401) {
        localStorage.removeItem('token');
        localStorage.removeItem('user');
        window.location.href = 'auth.html';
        return null;
    }

    const result = await response.json();
    return result.success ? result.user : null;
}

/**
 * 更新用户资料
 */
async function updateProfile(nickname) {
    const token = localStorage.getItem('token');
    if (!token) {
        window.location.href = 'auth.html';
        return;
    }

    const response = await fetch(`${API_BASE}/auth/profile`, {
        method: 'PUT',
        headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({ nickname })
    });
    return await response.json();
}

/**
 * 检查登录状态
 */
function checkAuth() {
    const token = localStorage.getItem('token');
    if (!token) {
        window.location.href = 'auth.html';
        return false;
    }
    return true;
}

/**
 * 获取用户信息
 */
function getUser() {
    const userStr = localStorage.getItem('user');
    return userStr ? JSON.parse(userStr) : null;
}

/**
 * 更新用户信息
 */
function updateUser(user) {
    localStorage.setItem('user', JSON.stringify(user));
}

/**
 * 重置密码
 */
async function resetPassword(email, code, newPassword) {
    // 加密新密码用于传输
    const encryptedPassword = encryptPassword(newPassword);

    const response = await fetch(`${API_BASE}/auth/reset-password`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            email,
            code,
            password: encryptedPassword,
            encrypted: true  // 标记密码已加密
        })
    });
    return await response.json();
}
