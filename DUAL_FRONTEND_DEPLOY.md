# 双前端部署指南

## 架构

```
┌─────────────────────┐
│ Vercel前端          │ ← 自己管理（无需备案）
│ https://xxx.vercel.app │
└──────────┬──────────┘
           │
           ├────────→ ┌──────────────────┐
           │          │ 后端API          │
           │          │ 111.228.8.17:5555 │
           │          └──────────────────┘
           │
           ↑
┌──────────┴──────────┐
│ 国内服务器前端       │ ← 国内用户访问（更快）
│ http://111.228.8.17:8000 │
└─────────────────────┘
```

## 部署步骤

### 步骤1：配置后端CORS

编辑 `backend/push_api.py` 第538-543行：

```python
ALLOWED_ORIGINS = [
    "http://111.228.8.17:8000",           # ✅ 已有（国内服务器前端）
    "http://localhost:8000",              # ✅ 已有（本地开发）
    "https://你的项目名.vercel.app",      # ⚠️ 替换成实际Vercel域名
    "https://你的自定义域名.com"           # 可选：自定义域名
]
```

**重启后端：**
```bash
# SSH到服务器
ssh root@111.228.8.17

# 重启Flask
pkill -f "python3.*push_api.py"
cd /path/to/724caixun/backend
nohup python3 push_api.py > /tmp/flask.log 2>&1 &
```

### 步骤2：部署前端到Vercel

**方法A：使用Vercel CLI（推荐）**

```bash
# 安装Vercel CLI
npm i -g vercel

# 登录（需要GitHub账号）
vercel login

# 部署
cd /Users/hesiyuan/Code/724caixun
vercel

# 按提示操作：
# - Set up and deploy: Y
# - Which scope: 选择你的账号
# - Link to existing project: N
# - Project name: 输入项目名（如 724caixun）
# - Directory: ./frontend
# - Override settings: N
```

**方法B：通过GitHub集成**

1. 推送代码到GitHub
2. 访问 https://vercel.com/new
3. 导入GitHub仓库
4. 设置：
   - Framework Preset: Other
   - Root Directory: `frontend`
   - Build Command: 留空
   - Output Directory: `/`

### 步骤3：配置Vercel环境变量

在Vercel Dashboard中设置环境变量：

1. 进入项目：https://vercel.com/你的用户名/你的项目名/settings/environment-variables
2. 添加变量：
   - **Key**: `BACKEND_URL`
   - **Value**: `http://111.228.8.17:5555`
   - **Environments**: ✅ Production ✅ Preview ✅ Development
3. 保存
4. 重新部署（会自动触发）

### 步骤4：验证部署

**测试国内服务器前端：**
```bash
# 浏览器访问
http://111.228.8.17:8000/admin.html

# 打开控制台检查
console.log(getApiBase());  // 应该输出: http://111.228.8.17:5555
```

**测试Vercel前端：**
```bash
# 浏览器访问
https://你的项目名.vercel.app/admin.html

# 打开控制台检查
console.log(getApiBase());  // 应该输出: http://111.228.8.17:5555
```

**测试API连接：**
两个前端都应该能：
- ✅ 正常加载
- ✅ 登录管理后台
- ✅ 查看统计数据
- ✅ 推送测试消息

## 使用说明

### 给自己用（推荐Vercel）
```
访问：https://你的项目名.vercel.app/admin.html
优点：国外访问快，无需备案
```

### 给国内用户用
```
访问：http://111.228.8.17:8000/index_user.html
优点：国内访问快，直连服务器
```

### 本地开发
```
访问：http://localhost:8000/admin.html
连接：http://localhost:5555
```

## 配置优先级

前端会按以下顺序查找后端URL：

1. **URL参数**：`?backend_url=http://xxx:5555`
2. **Meta标签**：`<meta name="backend-url">`
3. **Vercel环境变量**：`BACKEND_URL`
4. **localStorage**：`localStorage.getItem('backend_url')`
5. **默认配置**：根据访问域名自动判断

## 域名管理

### 添加自定义域名到Vercel

1. 在Vercel项目设置中添加域名
2. 在域名DNS管理中添加CNAME记录：
   ```
   CNAME  admin  ->  你的项目名.vercel.app
   ```
3. Vercel会自动签发SSL证书

### 更新CORS配置

添加自定义域名后，记得更新后端CORS：
```python
ALLOWED_ORIGINS = [
    "http://111.228.8.17:8000",
    "http://localhost:8000",
    "https://你的项目名.vercel.app",
    "https://admin.你的域名.com"  # 添加这里
]
```

## 故障排查

### 问题1：CORS错误
**症状**：浏览器控制台显示 `Access-Control-Allow-Origin`

**解决**：
1. 检查后端 `push_api.py` 的 `ALLOWED_ORIGINS`
2. 确认包含当前访问的域名
3. 重启后端服务

### 问题2：API请求404
**症状**：能打开页面，但数据加载失败

**解决**：
1. 打开浏览器控制台
2. 输入 `console.log(getApiBase())`
3. 检查返回的URL是否正确
4. 如果不对，清空localStorage或用URL参数指定

### 问题3：WebSocket连接失败
**症状**：消息推送不工作

**解决**：
1. 检查后端WebSocket服务是否运行：`ps aux | grep websocket`
2. 确认后端URL的协议：
   - HTTP前端 → 用 `ws://`
   - HTTPS前端 → 用 `wss://`（需要后端配置SSL）
3. 混合内容（HTTPS前端+HTTP后端）会被浏览器阻止

### 问题4：Vercel部署后前端还是旧的
**解决**：
1. Vercel有CDN缓存，等待几分钟
2. 或强制刷新：Ctrl+Shift+R (Windows) / Cmd+Shift+R (Mac)

## 维护建议

### 定期检查
- ✅ 每月检查Vercel带宽使用情况
- ✅ 监控后端服务器资源使用
- ✅ 备份数据库和配置文件

### 更新代码
```bash
# 后端更新
ssh root@111.228.8.17
cd /path/to/724caixun
git pull
pkill -f "python3.*push_api.py"
nohup python3 backend/push_api.py > /tmp/flask.log 2>&1 &

# 前端更新（Vercel自动部署）
git push
```

### 安全建议
- ✅ 后端API添加访问限流
- ✅ 使用强密码管理后台token
- ✅ 定期更新依赖包
- ✅ 配置防火墙只开放必要端口

## 成本估算

### Vercel免费版
- ✅ 100GB带宽/月
- ✅ 无限请求
- ✅ 自动SSL
- ❌ 无团队协作功能

### 超出免费额度
- Vercel Pro: $20/月
- 或切换到Netlify（100GB免费）
- 或自己部署前端（无额外成本）

## 下一步

1. ✅ 部署到Vercel
2. ✅ 测试两个前端都能正常工作
3. ✅ 配置自定义域名（可选）
4. ✅ 设置监控告警（可选）

有问题？查看详细文档：`VERCEL_DEPLOY.md`
