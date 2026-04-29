// 管理页面访问控制
const ADMIN_TOKEN = '724caixun_admin_2024_k9HxM7qL';

// 检查 URL 参数中的 admin_token
function checkAdminAccess() {
    const urlParams = new URLSearchParams(window.location.search);
    const token = urlParams.get('admin_token');

    if (token !== ADMIN_TOKEN) {
        document.body.innerHTML = `
            <div style="display: flex; justify-content: center; align-items: center; height: 100vh; font-family: Arial, sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);">
                <div style="background: white; padding: 40px; border-radius: 10px; text-align: center; box-shadow: 0 4px 12px rgba(0,0,0,0.15);">
                    <h1 style="color: #ef4444; margin-bottom: 20px;">🔒 访问被拒绝</h1>
                    <p style="color: #666; margin-bottom: 20px;">管理页面需要有效的访问令牌</p>
                    <p style="color: #999; font-size: 14px;">请联系管理员获取正确的访问链接</p>
                </div>
            </div>
        `;
        return false;
    }
    return true;
}

// 页面加载时验证
if (!checkAdminAccess()) {
    throw new Error('Unauthorized access');
}
