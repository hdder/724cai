const express = require('express');
const http = require('http');
const { Server } = require('socket.io');
const cors = require('cors');
const axios = require('axios');
const config = require('./config');

const app = express();
const server = http.createServer(app);

// 配置 CORS
const io = new Server(server, {
  cors: {
    origin: '*',
    methods: ['GET', 'POST']
  }
});

app.use(cors());
app.use(express.json());

// Flask 后端地址（从配置读取）
const FLASK_URL = config.FLASK_URL;

// Socket.IO 连接处理
io.on('connection', (socket) => {
  console.log(`[${new Date().toLocaleTimeString()}] WebSocket 连接: ${socket.id}`);

  // 连接时通知 Flask 创建会话
  axios.post(`${FLASK_URL}/api/ws/connect`, { socket_id: socket.id })
    .catch(err => console.error('创建会话失败:', err.message));

  // 监听订阅频道事件 - 转发给 Flask 处理
  socket.on('subscribe', async (channelIds) => {
    console.log(`用户 ${socket.id} 请求订阅:`, channelIds);

    try {
      await axios.post(`${FLASK_URL}/api/ws/subscribe`, {
        socket_id: socket.id,
        channel_ids: channelIds
      });
    } catch (err) {
      console.error('订阅失败:', err.message);
    }
  });

  // 监听切换频道事件 - 转发给 Flask 处理
  socket.on('switch_channel', async (channelId) => {
    console.log(`用户 ${socket.id} 切换频道: ${channelId}`);

    try {
      const response = await axios.post(`${FLASK_URL}/api/ws/switch-channel`, {
        socket_id: socket.id,
        channel_id: channelId
      });

      // 将未读数返回给前端
      socket.emit('unread_update', response.data.unread_counts);

      // 触发历史消息加载事件
      socket.emit('history_loaded', {
        channel_id: channelId,
        messages: response.data.history || []
      });
    } catch (err) {
      console.error('切换频道失败:', err.message);
    }
  });

  socket.on('disconnect', () => {
    console.log(`[${new Date().toLocaleTimeString()}] WebSocket 断开: ${socket.id}`);

    // 通知 Flask 删除会话
    axios.post(`${FLASK_URL}/api/ws/disconnect`, { socket_id: socket.id })
      .catch(err => console.error('删除会话失败:', err.message));
  });
});

// HTTP API: 推送消息（由 Flask 调用）
app.post('/api/push', async (req, res) => {
  const { channel_id, title, content, subscribers } = req.body;

  if (!channel_id || !content) {
    return res.status(400).json({ error: '缺少参数' });
  }

  try {
    const message = {
      channel_id,
      title: title || '',
      content,
      timestamp: Date.now() // 使用毫秒时间戳，前端会自动转换为本地时区
    };

    let pushCount = 0;

    // subscribers 是从 Flask 传入的 socket_id 列表，包含未读数信息
    if (subscribers && Array.isArray(subscribers)) {
      subscribers.forEach((subscriber) => {
        const socketId = subscriber.socket_id;
        const unreadCounts = subscriber.unread_counts;

        const socket = io.sockets.sockets.get(socketId);
        if (socket) {
          // 发送新消息
          socket.emit('new_message', message);

          // 发送未读数更新
          socket.emit('unread_update', unreadCounts);

          pushCount++;
        }
      });
    }

    console.log(`[${new Date().toLocaleTimeString()}] 推送到 [${channel_id}], ${pushCount} 用户`);
    console.log(`  内容: ${content.substring(0, 50)}`);

    res.json({ success: true, push_count: pushCount });
  } catch (error) {
    console.error('推送失败:', error);
    res.status(500).json({ error: '推送失败' });
  }
});

// 健康检查
app.get('/health', async (req, res) => {
  const sockets = await io.fetchSockets();
  res.json({
    status: 'ok',
    online_users: sockets.length,
    timestamp: new Date().toISOString()
  });
});

const PORT = process.env.PORT || config.WEBSOCKET_PORT;
server.listen(PORT, () => {
  console.log('='.repeat(50));
  console.log(`Socket.IO 推送服务启动成功`);
  console.log(`服务地址: http://localhost:${PORT}`);
  console.log(`职责: WebSocket 实时推送传输层`);
  console.log(`业务逻辑: 由 Flask 管理`);
  console.log(`Flask地址: ${FLASK_URL}`);
  console.log('='.repeat(50));
});
