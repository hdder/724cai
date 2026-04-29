#!/bin/bash

# 724财讯消息推送系统启动脚本
# 架构: Flask(业务逻辑中心) + Node.js(纯WebSocket传输层) + 前端

# 固定的访问 Token
ACCESS_TOKEN="724caixun_2024_token_k9HxM7qL"


echo "================================"
echo "  724财讯消息推送系统启动脚本"
echo "================================"
echo ""

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 检查是否在项目根目录
if [ ! -d "websocket" ] || [ ! -d "frontend" ] || [ ! -d "backend" ]; then
    echo -e "${RED}错误: 请在项目根目录运行此脚本${NC}"
    exit 1
fi

# 清理可能占用端口的旧进程（强制清理）
echo -e "${YELLOW}清理旧进程...${NC}"
pkill -9 -f "python.*-m http.server 8000" 2>/dev/null
pkill -9 -f "node.*/websocket/server.js" 2>/dev/null
pkill -9 -f "python.*push_api.py" 2>/dev/null
lsof -ti:8000 | xargs kill -9 2>/dev/null
lsof -ti:9080 | xargs kill -9 2>/dev/null
lsof -ti:5555 | xargs kill -9 2>/dev/null
sleep 2
echo -e "${GREEN}✓ 旧进程已强制清理${NC}"
echo ""

# 检查 Node.js
if ! command -v node &> /dev/null; then
    echo -e "${RED}错误: 未安装 Node.js${NC}"
    exit 1
fi

# 检查 Python
if ! command -v python3 &> /dev/null && ! command -v python &> /dev/null; then
    echo -e "${RED}错误: 未安装 Python${NC}"
    exit 1
fi

echo -e "${GREEN}✓ 环境检查通过${NC}"
echo ""

# 1. 安装 Node.js 依赖
echo -e "${YELLOW}[1/4] 检查 Node.js 依赖...${NC}"
cd websocket
if [ ! -d "node_modules" ]; then
    echo "安装 Node.js 依赖..."
    npm install
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ Node.js 依赖安装成功${NC}"
    else
        echo -e "${RED}✗ Node.js 依赖安装失败${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}✓ Node.js 依赖已存在${NC}"
fi
cd ..

# 2. 安装 Python 依赖
echo -e "${YELLOW}[2/4] 安装 Python 依赖...${NC}"
if [ -d "backend/venv" ]; then
    echo "使用现有虚拟环境: backend/venv"

    # 每次都检查并安装/更新依赖（pip会自动跳过已安装的包）
    source backend/venv/bin/activate
    echo "检查并安装 Python 依赖..."
    pip install -r backend/requirements.txt
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ Python 依赖检查完成${NC}"
    else
        echo -e "${RED}✗ Python 依赖安装失败${NC}"
        exit 1
    fi
    deactivate
else
    echo -e "${YELLOW}未找到虚拟环境,正在创建...${NC}"
    python3 -m venv backend/venv
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ 虚拟环境创建成功${NC}"
        source backend/venv/bin/activate
        pip install -r backend/requirements.txt
        if [ $? -eq 0 ]; then
            echo -e "${GREEN}✓ Python 依赖安装成功${NC}"
        else
            echo -e "${RED}✗ Python 依赖安装失败${NC}"
            exit 1
        fi
        deactivate
    else
        echo -e "${RED}✗ 虚拟环境创建失败${NC}"
        exit 1
    fi
fi

# 3. 启动服务
echo ""
echo -e "${YELLOW}[3/4] 启动服务...${NC}"

# 创建日志目录
mkdir -p logs

# 启动 Flask 后端(先启动,因为 Node.js 依赖它)
echo "启动 Flask 后端服务 (端口 5555)..."
source backend/venv/bin/activate
cd backend
nohup python3 push_api.py > ../logs/flask.log 2>&1 &
FLASK_PID=$!
echo $FLASK_PID > ../logs/flask.pid
cd ..
deactivate
echo -e "${GREEN}✓ Flask 后端已启动 (PID: $FLASK_PID)${NC}"

# 等待 Flask 启动
sleep 3

# 启动 Node.js 推送服务
echo "启动 Node.js WebSocket 传输层 (端口 9080)..."
cd websocket
npm start > ../logs/nodejs.log 2>&1 &
NODE_PID=$!
echo $NODE_PID > ../logs/nodejs.pid
cd ..
echo -e "${GREEN}✓ Node.js WebSocket 已启动 (PID: $NODE_PID)${NC}"

# 等待 Node.js 启动
sleep 2

# 启动前端 HTTP 服务器
echo "启动前端 HTTP 服务器 (端口 8000)..."
cd frontend
nohup python3 -m http.server 8000 > ../logs/frontend.log 2>&1 &
FRONTEND_PID=$!
echo $FRONTEND_PID > ../logs/frontend.pid
cd ..
echo -e "${GREEN}✓ 前端服务已启动 (PID: $FRONTEND_PID)${NC}"

# 4. 服务信息
echo ""
echo -e "${YELLOW}[4/5] 服务启动完成!${NC}"
echo "================================"
echo "服务架构:"
echo "  Flask (Port 5555)   → 业务逻辑中心 + 数据库"
echo "  Node.js (Port 9080)  → 纯 WebSocket 传输层"
echo "  Frontend (Port 8000) → 静态页面"
echo ""
echo "服务信息:"
echo ""

# 获取本机 IP 地址
LOCAL_IP=$(ifconfig | grep "inet " | grep -v 127.0.0.1 | awk '{print $2}' | head -n 1)

# 尝试获取公网 IP
echo -n "正在获取公网 IP..."
PUBLIC_IP=$(curl -s --max-time 3 ifconfig.me 2>/dev/null || curl -s --max-time 3 ipinfo.io/ip 2>/dev/null || echo "")
if [ ! -z "$PUBLIC_IP" ]; then
    echo -e " ${GREEN}$PUBLIC_IP${NC}"
else
    echo " ${YELLOW}获取失败（可能需要开放防火墙）${NC}"
fi

echo ""
echo -e "${GREEN}╔════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  🔐   安全访问 Token（复制下面的地址）            ║${NC}"
echo -e "${GREEN}╠══════════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║  ${YELLOW}$ACCESS_TOKEN${NC}                       ║${NC}"
echo -e "${GREEN}╠══════════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║  ℹ️  将此地址发送给朋友，需要 token 才能访问        ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════╝${NC}"
echo ""
echo "📍 安全访问地址（复制这个给朋友）:"
if [ ! -z "$LOCAL_IP" ]; then
    echo -e "   ${YELLOW}http://$LOCAL_IP:8000?token=$ACCESS_TOKEN${NC}"
fi
if [ ! -z "$PUBLIC_IP" ]; then
    echo -e "   ${GREEN}http://$PUBLIC_IP:8000?token=$ACCESS_TOKEN${NC}"
fi
echo ""
echo "⚙️  频道管理页面（管理 token 和测试）:"
if [ ! -z "$LOCAL_IP" ]; then
    echo -e "   ${YELLOW}http://$LOCAL_IP:8000/admin.html?admin_token=724caixun_admin_2024_k9HxM7qL${NC}"
fi
if [ ! -z "$PUBLIC_IP" ]; then
    echo -e "   ${GREEN}http://$PUBLIC_IP:8000/admin.html?admin_token=724caixun_admin_2024_k9HxM7qL${NC}"
fi
echo ""
echo "📊 服务状态:"
echo "   Flask 后端 (业务逻辑): PID $FLASK_PID (端口 5555)"
echo "   Node.js (WebSocket传输): PID $NODE_PID (端口 9080)"
echo "   前端服务:              PID $FRONTEND_PID (端口 8000)"
echo ""
echo "🔌 外部接口（给朋友/程序用）:"
echo "   POST http://localhost:5555/push/send?channel_token=xxx"
if [ ! -z "$PUBLIC_IP" ]; then
    echo -e "   ${GREEN}POST http://$PUBLIC_IP:5555/push/send?channel_token=xxx${NC}"
fi
echo ""
echo "📝 日志文件:"
echo "   Flask:   logs/flask.log"
echo "   Node.js: logs/nodejs.log"
echo "   前端:    logs/frontend.log"
echo ""

# 5. 端口连通性检测
echo ""
echo -e "${YELLOW}[5/5] 端口连通性检测${NC}"
echo "================================"

# 等待服务完全启动
echo "等待服务完全启动..."
sleep 3

# 检测端口连通性
check_local_port() {
    local port=$1
    local name=$2

    # 检查端口是否在监听
    if netstat -an | grep -q "\.$port.*LISTEN" 2>/dev/null || lsof -i :$port > /dev/null 2>&1; then
        # 尝试访问端口
        if curl -s --connect-timeout 2 http://localhost:$port > /dev/null 2>&1; then
            echo -e "  ${GREEN}✓${NC} 端口 $port ($name) - 监听中且可访问"
            return 0
        else
            echo -e "  ${YELLOW}⚠${NC}  端口 $port ($name) - 正在监听但访问失败"
            return 1
        fi
    else
        echo -e "  ${RED}✗${NC} 端口 $port ($name) - 未监听"
        return 2
    fi
}

check_local_port "5555" "Flask API"
check_local_port "9080" "WebSocket服务"
check_local_port "8000" "前端服务"

echo ""
echo -e "${YELLOW}防火墙配置提示:${NC}"
echo "如果外网无法访问，请检查云服务器安全组设置："
echo ""
echo "  协议    端口      说明"
echo "  TCP    5555     Flask API 接口"
echo "  TCP    9080     WebSocket 连接"
echo "  TCP    8000     前端页面访问"
echo ""
echo "京东云配置路径："
echo "  控制台 → 云主机 → 实例 → 安全组 → 配置规则"
echo ""

echo ""
echo "================================"
echo "🛑 停止服务: ./stop.sh"
echo "================================"
echo ""
echo "✓ 所有服务已在后台启动"

