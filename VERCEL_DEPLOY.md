# Vercel部署指南

## 架构说明

```
┌─────────────────┐
│  Vercel前端     │ (国外，无需备案)
│  (HTTPS)        │
└────────┬────────┘
         │ HTTPS请求
         ↓
┌─────────────────┐
│ 国内服务器后端  │ (Flask + WebSocket)
│ :5555 API       │
│ :9080 WS        │
└─────────────────┘
```

## 部署步骤

### 1. 准备后端服务器

确保国内服务器已运行：
- Flask后端 (5555端口)
- WebSocket服务器 (9080端口)
- 已配置CORS允许Vercel域名

### 2. 修改后端CORS配置

编辑 `backend/push_api.py`，添加你的Vercel域名：

```python
ALLOWED_ORIGINS = [
    "http://111.228.8.17:8000",  # 当前前端
    "http://localhost:8000",     # 本地开发
    "https://你的项目名.vercel.app",  # ⚠️ 修改这里
    "https://你的自定义域名.com"  # 如果有自定义域名
]
```

重启后端服务。

### 3. Vercel环境变量设置

在Vercel项目中设置环境变量：

**方法A：通过Vercel Dashboard**
1. 进入项目 Settings → Environment Variables
2. 添加变量：
   - Name: `BACKEND_URL`
   - Value: `http://111.228.8.17:5555`（你的后端地址）
   - Environments: Production, Preview, Development

**方法B：通过vercel.json**
已配置在 `vercel.json` 中，修改 `BACKEND_URL` 为你的后端地址。

### 4. 部署到Vercel

**通过Vercel CLI：**

```bash
# 安装Vercel CLI
npm i -g vercel

# 登录
vercel login

# 部署
cd /Users/hesiyuan/Code/724caixun
vercel
```

**通过GitHub集成：**
1. 将代码推送到GitHub
2. 在Vercel导入项目
3. 自动部署

### 5. 域名配置（可选）

**使用自定义域名：**
1. 在Vercel项目设置中添加域名
2. 在域名DNS中添加CNAME记录指向Vercel
3. 更新后端CORS配置允许新域名

**使用Vercel默认域名：**
- Vercel会自动分配：`https://你的项目名.vercel.app`

## 前端配置说明

前端会自动检测环境并配置后端URL：

### 优先级（从高到低）：

1. **URL参数**：`?backend_url=http://xxx:5555`
2. **Meta标签**：`<meta name="backend-url" content="...">`
3. **全局变量**：`window.BACKEND_URL`
4. **localStorage**：`localStorage.getItem('backend_url')`
5. **默认值**：`http://111.228.8.17:5555`

### 手动设置后端URL（3种方法）

**方法1：URL参数**
```
https://你的项目名.vercel.app/admin.html?backend_url=http://111.228.8.17:5555
```

**方法2：localStorage**
在浏览器控制台执行：
```javascript
localStorage.setItem('backend_url', 'http://111.228.8.17:5555');
location.reload();
```

**方法3：修改HTML**
在 `frontend/admin.html` 的 `<head>` 中添加：
```html
<meta name="backend-url" content="http://111.228.8.17:5555">
```

## WebSocket配置

WebSocket会自动使用后端URL并转换协议：
- HTTP → `ws://`
- HTTPS → `wss://`

如果后端不支持WSS，需要使用反向代理（Nginx）。

## 注意事项

1. **HTTPS访问**：Vercel强制HTTPS，确保后端API支持HTTPS或配置反向代理
2. **CORS错误**：如果遇到跨域错误，检查后端CORS配置
3. **WebSocket连接**：如果后端是HTTP，前端HTTPS会导致混合内容错误，需要后端也启用HTTPS
4. **环境变量**：修改环境变量后需要重新部署才能生效

## 常见问题

### Q: 浏览器控制台出现CORS错误
A: 检查后端 `push_api.py` 的 `ALLOWED_ORIGINS` 是否包含你的Vercel域名

### Q: WebSocket连接失败
A:
1. 检查后端WebSocket服务是否运行
2. 确认后端URL的协议（HTTP用ws://，HTTPS用wss://）
3. 混合内容（HTTPS前端+HTTP后端）会被浏览器阻止

### Q: API请求404
A: 检查 `config.js` 中的 `getApiBase()` 返回的URL是否正确

### Q: 如何本地测试Vercel部署后的配置？
A: 使用URL参数：
```
http://localhost:8000/admin.html?backend_url=http://111.228.8.17:5555
```

## 生产环境建议

1. **后端HTTPS**：使用Let's Encrypt或Cloudflare为后端配置HTTPS
2. **CDN加速**：国内用户访问Vercel可能较慢，可配置Cloudflare CDN
3. **监控日志**：配置Vercel Analytics和后端日志监控
4. **数据库备份**：定期备份SQLite数据库或迁移到PostgreSQL
