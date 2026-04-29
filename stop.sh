#!/bin/bash

# 消息推送系统停止脚本

echo "================================"
echo "  停止消息推送系统服务"
echo "================================"
echo ""

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# 停止前端
if [ -f "logs/frontend.pid" ]; then
    PID=$(cat logs/frontend.pid)
    if ps -p $PID > /dev/null 2>&1; then
        echo "停止前端服务 (PID: $PID)..."
        kill $PID
        echo -e "${GREEN}✓ 前端服务已停止${NC}"
    else
        echo -e "${YELLOW}⚠ 前端服务未运行${NC}"
    fi
    rm -f logs/frontend.pid
else
    echo -e "${YELLOW}⚠ 未找到前端 PID 文件${NC}"
fi

# 停止 Node.js
if [ -f "logs/nodejs.pid" ]; then
    PID=$(cat logs/nodejs.pid)
    if ps -p $PID > /dev/null 2>&1; then
        echo "停止 Node.js 服务 (PID: $PID)..."
        kill $PID
        echo -e "${GREEN}✓ Node.js 服务已停止${NC}"
    else
        echo -e "${YELLOW}⚠ Node.js 服务未运行${NC}"
    fi
    rm -f logs/nodejs.pid
else
    echo -e "${YELLOW}⚠ 未找到 Node.js PID 文件${NC}"
fi

# 停止 Flask
if [ -f "logs/flask.pid" ]; then
    PID=$(cat logs/flask.pid)
    if ps -p $PID > /dev/null 2>&1; then
        echo "停止 Flask Push API (PID: $PID)..."
        kill $PID
        echo -e "${GREEN}✓ Flask Push API 已停止${NC}"
    else
        echo -e "${YELLOW}⚠ Flask Push API 未运行${NC}"
    fi
    rm -f logs/flask.pid
else
    echo -e "${YELLOW}⚠ 未找到 Flask Push API PID 文件${NC}"
fi

# 检查是否有残留进程
echo ""
echo "检查残留进程..."

# 检查 Node.js 进程（仅本项目）
NODE_PROCS=$(ps aux | grep "node.*/Users/hesiyuan/Code/724caixun/websocket/server.js" | grep -v grep | wc -l)
if [ $NODE_PROCS -gt 0 ]; then
    echo -e "${YELLOW}发现 $NODE_PROCS 个 WebSocket 残留进程,正在清理...${NC}"
    pkill -9 -f "node.*/Users/hesiyuan/Code/724caixun/websocket/server.js"
    echo -e "${GREEN}✓ 已清理所有 WebSocket 进程${NC}"
fi

# 检查 Flask 进程（仅本项目）
FLASK_PROCS=$(ps aux | grep "python.*push_api.py" | grep -v grep | wc -l)
if [ $FLASK_PROCS -gt 0 ]; then
    echo -e "${YELLOW}发现 $FLASK_PROCS 个 Flask Push API 残留进程,正在清理...${NC}"
    pkill -9 -f "python.*push_api.py"
    echo -e "${GREEN}✓ 已清理所有 Flask Push API 进程${NC}"
fi

echo ""
echo -e "${GREEN}================================"
echo "  所有服务已停止"
echo "================================${NC}"
