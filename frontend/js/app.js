// 全局变量
let socket = null;
let currentChannel = null;
let channels = {};
let unreadCounts = {};
let totalMessageCount = 0;
let channelMessageCount = 0;

// API 基础 URL
const API_BASE = window.getApiBase ? window.getApiBase() : `http://${window.location.hostname}:5555`;

// 分页加载相关
let currentOffset = 0;
let totalMessages = 0;
let isLoadingMore = false;
let hasMoreMessages = true;
const INITIAL_LOAD = 40;  // 初始加载40条
const LOAD_MORE = 25;     // 每次加载25条
const SCROLL_THRESHOLD = 60;  // 距离顶部60px时加载
const BOTTOM_THRESHOLD = 100;  // 距离底部100px时认为在底部
let isAtBottom = true;  // 是否在底部

// 初始化应用
async function init() {
    await loadChannels();
    connectWebSocket();
    renderChannelList();
}

// 加载频道列表
async function loadChannels() {
    try {
        const host = window.location.hostname;
        const response = await fetch(`${API_BASE}/api/channels`);
        const data = await response.json();

        channels = {};
        data.channels.forEach(channel => {
            channels[channel.id] = channel;
        });

        console.log('频道列表加载成功:', channels);
    } catch (error) {
        console.error('加载频道列表失败:', error);
    }
}

// 连接 WebSocket
function connectWebSocket() {
    // 自动获取当前页面的主机地址
    const host = window.location.hostname;
    const socketUrl = `http://${host}:9080`;

    console.log('连接到 Socket.IO 服务器:', socketUrl);
    socket = io(socketUrl, {
        transports: ['websocket', 'polling']
    });

    socket.on('connect', () => {
        console.log('✓ WebSocket 连接成功');
        updateConnectionStatus(true);

        // 订阅所有频道
        const allChannelIds = Object.keys(channels);
        socket.emit('subscribe', allChannelIds);
        console.log('订阅频道:', allChannelIds);
    });

    socket.on('disconnect', () => {
        console.log('✗ WebSocket 连接断开');
        updateConnectionStatus(false);
    });

    socket.on('reconnect', () => {
        console.log('✓ WebSocket 重新连接');
        updateConnectionStatus(true);
    });

    // 接收新消息
    socket.on('new_message', (message) => {
        console.log('收到新消息:', message);
        handleNewMessage(message);
    });

    // 更新未读数
    socket.on('unread_update', (unread) => {
        unreadCounts = unread;
        renderChannelList();
    });

    // 监听历史消息加载
    socket.on('history_loaded', (data) => {
        console.log(`加载频道 ${data.channel_id} 的历史消息: ${data.messages.length} 条`);
        const container = document.getElementById('messageContainer');

        // 处理分页信息
        if (data.pagination) {
            totalMessages = data.pagination.total;
            hasMoreMessages = data.pagination.has_more;
        }

        // 如果是初始加载(offset=0),清空容器
        if (currentOffset === 0) {
            container.innerHTML = '';
        }

        // 移除加载提示
        const loadingTip = container.querySelector('.loading-more');
        if (loadingTip) loadingTip.remove();

        if (data.messages.length > 0) {
            // 判断是否是初始加载(禁用动画避免闪烁)
            const isInitialLoad = currentOffset === 0;

            // 使用 DocumentFragment 批量添加,避免逐条添加导致的滚动问题
            const fragment = document.createDocumentFragment();

            data.messages.forEach(msg => {
                const messageEl = createMessageElement(msg, isInitialLoad);
                fragment.appendChild(messageEl);
            });

            // 一次性添加所有消息
            container.appendChild(fragment);

            // 更新已加载数量
            channelMessageCount += data.messages.length;
            currentOffset += data.messages.length;

            // 如果是加载更多,恢复滚动位置
            if (currentOffset > data.messages.length) {
                // 需要在添加前记录位置,这里重新计算
                // 由于是添加到顶部,需要调整scrollTop
                const scrollHeight = container.scrollHeight;
                const firstMessage = container.querySelector('.message-item');
                if (firstMessage) {
                    container.scrollTop = firstMessage.offsetTop;
                }
            } else {
                // 初始加载,滚动到底部
                container.scrollTop = container.scrollHeight;
                // 初始加载后,标记为在底部
                isAtBottom = true;
            }

            isLoadingMore = false;
        } else if (currentOffset === 0) {
            container.innerHTML = '<div class="welcome-message"><p>暂无消息</p></div>';
            channelMessageCount = 0;
            hasMoreMessages = false;
            isLoadingMore = false;
        } else {
            // 没有更多消息了
            hasMoreMessages = false;
            isLoadingMore = false;
        }

        updateStats();
    });

    // 添加滚动监听 - 实现自动加载更多
    setupScrollListener();
}

// 设置滚动监听
function setupScrollListener() {
    const container = document.getElementById('messageContainer');

    // 使用防抖优化性能
    let scrollTimeout;
    container.addEventListener('scroll', () => {
        if (scrollTimeout) {
            clearTimeout(scrollTimeout);
        }

        scrollTimeout = setTimeout(() => {
            // 检查是否接近顶部
            if (container.scrollTop <= SCROLL_THRESHOLD &&
                hasMoreMessages &&
                !isLoadingMore &&
                currentChannel) {
                loadMoreMessages();
            }

            // 更新是否在底部的状态
            updateBottomStatus(container);
        }, 100);
    });
}

// 更新底部状态
function updateBottomStatus(container) {
    const distanceToBottom = container.scrollHeight - container.scrollTop - container.clientHeight;
    isAtBottom = distanceToBottom <= BOTTOM_THRESHOLD;
}

// 加载更多历史消息
function loadMoreMessages() {
    isLoadingMore = true;

    // 显示加载提示
    const container = document.getElementById('messageContainer');
    const loadingTip = document.createElement('div');
    loadingTip.className = 'loading-more';
    loadingTip.style.cssText = 'text-align: center; padding: 10px; color: #7f8c8d; font-size: 14px;';
    loadingTip.textContent = '加载更多消息...';
    container.insertBefore(loadingTip, container.firstChild);

    // 通过 Node.js 服务转发到 Flask
    // 直接调用 Flask API
    const host = window.location.hostname;
    fetch(`${API_BASE}/api/ws/switch-channel`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            socket_id: socket.id,
            channel_id: currentChannel,
            limit: LOAD_MORE,
            offset: currentOffset
        })
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            // 手动触发加载逻辑(模拟 socket.on('history_loaded'))
            const historyData = {
                channel_id: currentChannel,
                messages: data.history,
                pagination: data.pagination
            };

            // 触发 history_loaded 事件处理
            const event = new CustomEvent('history_loaded', { detail: historyData });
            socket.emit('history_loaded', historyData);

            // 手动调用处理逻辑
            handleHistoryLoaded(historyData);
        }
    })
    .catch(err => {
        console.error('加载更多消息失败:', err);
        isLoadingMore = false;
        const loadingTip = container.querySelector('.loading-more');
        if (loadingTip) loadingTip.remove();
    });
}

// 处理历史消息加载(提取为独立函数)
function handleHistoryLoaded(data) {
    const container = document.getElementById('messageContainer');

    // 处理分页信息
    if (data.pagination) {
        totalMessages = data.pagination.total;
        hasMoreMessages = data.pagination.has_more;
    }

    // 移除加载提示
    const loadingTip = container.querySelector('.loading-more');
    if (loadingTip) loadingTip.remove();

    if (data.messages.length > 0) {
        // 记录当前滚动位置
        const oldScrollHeight = container.scrollHeight;
        const oldScrollTop = container.scrollTop;

        data.messages.forEach(msg => {
            displayMessage(msg, false, true);  // 加载更多时也禁用动画
        });

        // 更新已加载数量
        channelMessageCount += data.messages.length;
        currentOffset += data.messages.length;

        // 恢复滚动位置
        const newScrollHeight = container.scrollHeight;
        container.scrollTop = oldScrollTop + (newScrollHeight - oldScrollHeight);

        isLoadingMore = false;
    } else {
        hasMoreMessages = false;
        isLoadingMore = false;
    }

    updateStats();
}

// 更新连接状态
function updateConnectionStatus(connected) {
    const statusDot = document.querySelector('.status-dot');
    const statusText = document.querySelector('.status-text');

    if (connected) {
        statusDot.className = 'status-dot connected';
        statusText.textContent = '已连接';
    } else {
        statusDot.className = 'status-dot disconnected';
        statusText.textContent = '连接断开';
    }
}

// 渲染频道列表
function renderChannelList() {
    const channelList = document.getElementById('channelList');
    channelList.innerHTML = '';

    Object.entries(channels).forEach(([id, channel]) => {
        const item = document.createElement('div');
        item.className = 'channel-item';
        if (id === currentChannel) {
            item.classList.add('active');
        }

        const unreadCount = unreadCounts[id] || 0;

        item.innerHTML = `
            <div class="channel-name">${channel.name}</div>
            <div class="channel-badge ${unreadCount > 0 ? 'show' : ''}">${unreadCount}</div>
        `;

        item.addEventListener('click', () => switchChannel(id));
        channelList.appendChild(item);
    });
}

// 切换频道
function switchChannel(channelId) {
    currentChannel = channelId;
    const channel = channels[channelId];

    // 重置分页状态
    currentOffset = 0;
    channelMessageCount = 0;
    hasMoreMessages = true;
    isLoadingMore = false;

    // 更新 UI
    document.getElementById('currentChannelName').textContent = channel.name;
    document.getElementById('currentChannelDesc').textContent = channel.description;

    // 清空消息区域，显示加载中
    const container = document.getElementById('messageContainer');
    container.innerHTML = '<div class="welcome-message"><p>加载中...</p></div>';

    // 更新频道列表高亮
    renderChannelList();

    // 通知服务器切换频道（传递初始加载参数）
    socket.emit('switch_channel', channelId);
    console.log('切换到频道:', channel.name);
}

// 处理新消息
function handleNewMessage(message) {
    totalMessageCount++;

    console.log('收到消息:', message);
    console.log('当前频道:', currentChannel);

    // 如果是当前频道的消息，显示在界面上
    if (message.channel_id === currentChannel) {
        channelMessageCount++;
        // 根据是否在底部决定是否自动滚动
        displayMessage(message, isAtBottom);
    } else {
        console.log('消息不属于当前频道，不显示。目标频道:', message.channel_id);
    }

    updateStats();
}

// 创建消息元素(不添加到DOM)
function createMessageElement(message, disableAnimation = false) {
    const messageEl = document.createElement('div');
    messageEl.className = 'message-item';
    if (disableAnimation) {
        messageEl.style.animation = 'none';
    }

    // 处理时间戳
    let time = '';
    if (message.timestamp) {
        try {
            time = new Date(message.timestamp).toLocaleString('zh-CN');
        } catch (e) {
            time = '';
        }
    }

    // 使用 marked.js 渲染 Markdown 内容
    let renderedContent = message.content;

    // 检查 marked 是否可用
    if (typeof marked !== 'undefined') {
        try {
            // 使用 marked.parse (v4+) 或 marked (v3-)
            const parseFn = marked.parse || marked;
            renderedContent = parseFn(message.content);
        } catch (e) {
            console.error('Markdown 解析失败:', e);
            renderedContent = message.content;
        }
    }

    messageEl.innerHTML = `
        <div class="message-title">${message.title}</div>
        <div class="message-content">${renderedContent}</div>
        ${time ? `<div class="message-time">${time}</div>` : ''}
    `;

    // 为图片添加错误处理
    const images = messageEl.querySelectorAll('img');
    images.forEach(img => {
        img.onerror = function() {
            console.error('图片加载失败:', this.src);
            this.style.display = 'none';
            // 显示错误提示
            const errorMsg = document.createElement('div');
            errorMsg.style.color = '#e74c3c';
            errorMsg.style.fontSize = '12px';
            errorMsg.textContent = `图片加载失败`;
            this.parentNode.insertBefore(errorMsg, this.nextSibling);
        };
    });

    return messageEl;
}

// 显示消息
function displayMessage(message, scroll = true, disableAnimation = false) {
    const container = document.getElementById('messageContainer');

    // 移除欢迎消息
    const welcome = container.querySelector('.welcome-message');
    if (welcome) {
        welcome.remove();
    }

    const messageEl = createMessageElement(message, disableAnimation);
    container.appendChild(messageEl);

    // 滚动到底部
    if (scroll) {
        container.scrollTop = container.scrollHeight;
    }
}

// 更新统计
function updateStats() {
    document.getElementById('totalMessages').textContent = totalMessageCount;
    document.getElementById('channelMessages').textContent = channelMessageCount;
}

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', init);
