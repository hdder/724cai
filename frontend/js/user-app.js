// 全局变量
let socket = null;
let currentChannel = null;
let currentTab = 'public'; // 'private' or 'public'
let currentCategory = 'all'; // 当前选中的分类
let isDarkMode = false;
let isLoggedIn = false;

// API 基础 URL
const API_BASE = window.getApiBase ? window.getApiBase() : `http://${window.location.hostname}:5555`;

// 获取用户信息（从localStorage）
function getUser() {
    const userStr = localStorage.getItem('user');
    return userStr ? JSON.parse(userStr) : null;
}

// 真实数据
let allChannels = [];  // 所有频道
let unreadCounts = {};  // 未读数映射
let allCategories = [];  // 所有标签（从API加载）
let categoriesCache = {
    public: null,
    private: null
};  // 标签缓存（懒加载）
let channelLatestMessage = {};  // 每个频道的最新消息
let channelLatestTime = {};  // 每个频道的最新消息时间
let channelMessageOffset = {};  // 每个频道已加载的消息数量（用于分页）
let channelMessageTotal = {};  // 每个频道的总消息数
let isLoadingMore = false;  // 是否正在加载更多消息
let channelMessagesCache = {};  // 频道消息缓存 {channelId: {messages: [], offset: 0, total: 0}}
let loadedChannels = new Set();  // 已加载过的频道ID集合
let doubaoRefreshInterval = null;  // 豆包总结刷新定时器
let doubaoOffset = {};  // 每个频道已加载的豆包分析数量（用于分页）
let doubaoTotal = {};  // 每个频道的豆包分析总数
let isLoadingMoreDoubao = false;  // 是否正在加载更多豆包分析

// 频道列表分页状态
let channelsPage = 1;  // 当前页码
let channelsPageSize = 20;  // 每页数量
let channelsTotal = 0;  // 频道总数
let hasMoreChannels = false;  // 是否还有更多频道
let isLoadingMoreChannels = false;  // 是否正在加载更多频道

// channels-summary API分页状态
let summaryPage = 1;  // 当前页码
let summaryPageSize = 20;  // 每页数量
let summaryTotal = 0;  // 总数
let hasMoreSummary = false;  // 是否还有更多
let isLoadingMoreSummary = false;  // 是否正在加载更多摘要

// 加载遮罩函数
function showLoading() {
    const overlay = document.getElementById('loadingOverlay');
    if (overlay) {
        overlay.classList.add('show');
    }
}

function hideLoading() {
    const overlay = document.getElementById('loadingOverlay');
    if (overlay) {
        overlay.classList.remove('show');
    }
}

// Token刷新状态（防止并发刷新）
let isRefreshing = false;
let refreshSubscribers = [];

// 添加等待刷新完成的订阅者
function subscribeTokenRefresh(callback) {
    refreshSubscribers.push(callback);
}

// 通知所有订阅者token已刷新
function onRefreshed(newToken) {
    refreshSubscribers.forEach(callback => callback(newToken));
    refreshSubscribers = [];
}

// 刷新access token
async function refreshAccessToken() {
    const refreshToken = localStorage.getItem('refresh_token');

    if (!refreshToken) {
        throw new Error('No refresh token available');
    }

    const response = await fetch(`${getApiBase()}/api/auth/refresh`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ refresh_token: refreshToken })
    });

    if (response.status === 401) {
        // Refresh token也过期了，需要重新登录
        localStorage.removeItem('token');
        localStorage.removeItem('refresh_token');
        localStorage.removeItem('user');
        window.location.href = 'auth.html';
        throw new Error('Refresh token expired');
    }

    if (!response.ok) {
        throw new Error('Refresh request failed');
    }

    const data = await response.json();

    if (data.success) {
        // 保存新的access token
        localStorage.setItem('token', data.token);
        return data.token;
    } else {
        throw new Error(data.message || 'Refresh failed');
    }
}

// 包装fetch，自动处理401刷新token
async function authenticatedFetch(url, options = {}) {
    // 确保headers对象存在
    if (!options.headers) {
        options.headers = {};
    }

    // 添加Authorization header
    const token = localStorage.getItem('token');
    if (token) {
        options.headers['Authorization'] = `Bearer ${token}`;
    }

    let response = await fetch(url, options);

    // 如果401且不是刷新接口，尝试刷新token
    if (response.status === 401 && !url.includes('/api/auth/refresh')) {
        if (isRefreshing) {
            // 如果正在刷新，等待刷新完成
            return new Promise((resolve, reject) => {
                subscribeTokenRefresh((newToken) => {
                    options.headers['Authorization'] = `Bearer ${newToken}`;
                    fetch(url, options).then(resolve).catch(reject);
                });
            });
        }

        // 开始刷新
        isRefreshing = true;

        try {
            const newToken = await refreshAccessToken();
            isRefreshing = false;

            // 通知所有等待的请求
            onRefreshed(newToken);

            // 用新token重试原请求
            options.headers['Authorization'] = `Bearer ${newToken}`;
            response = await fetch(url, options);
        } catch (error) {
            isRefreshing = false;
            refreshSubscribers = [];
            throw error;
        }
    }

    return response;
}


// 初始化应用
async function init() {
    // 不再强制检查登录，允许游客浏览公开消息
    // 更新认证按钮显示
    updateAuthButton();

    setupTheme();
    // 初始化 WebSocket 状态为离线
    updateWSStatus(false);

    // 初始化标签按钮样式（默认公开消息）
    updateTabButtons();

    await loadChannels();
    await loadCategories();

    // 先渲染一次频道列表（显示频道，但还没消息和未读数）
    renderChannelList();

    // 立即加载最新消息和未读数
    await loadAllChannelsLatestMessages();

    // 数据加载完成后，重新渲染（显示最新消息和未读数）
    renderChannelList();

    connectWebSocket();
    startCategoriesRefresh(); // 启动定时刷新标签
    startChannelsRefresh(); // 启动定时刷新频道（包括头像）
    setupScrollListener(); // 设置滚动监听
    // 大厂做法：切换标签不刷新，完全靠WebSocket推送 + 后台定时刷新
}

// 设置滚动监听（加载更多历史消息）
function setupScrollListener() {
    const container = document.getElementById('messageContainer');

    // 使用防抖，避免频繁触发
    let scrollTimeout = null;

    container.addEventListener('scroll', () => {
        if (scrollTimeout) clearTimeout(scrollTimeout);

        scrollTimeout = setTimeout(() => {
            // 当滚动到上方 20% 时就开始加载
            const scrollRatio = container.scrollTop / (container.scrollHeight - container.clientHeight);
            if (scrollRatio < 0.2) {
                loadMoreMessages();
            }
        }, 100); // 100ms 防抖
    });
}

// 加载频道列表（支持分页）
async function loadChannels(isLoadMore = false) {
    try {
        const host = window.location.hostname;
        const user = getUser();
        const page = isLoadMore ? channelsPage : 1;

        let url = `${API_BASE}/api/channels`;

        // 根据当前tab决定是否传递socket_id
        // 公开tab：不传socket_id，只获取公开频道
        // 私人tab：传递socket_id，获取订阅的私人频道
        if (currentTab === 'private' && user && user.id) {
            url += `?socket_id=${user.id}`;
        }

        url += `${url.includes('?') ? '&' : '?'}page=${page}&size=${channelsPageSize}`;

        const response = await fetch(url);
        const data = await response.json();

        if (data.channels) {
            let newChannels = [];
            if (isLoadMore) {
                newChannels = data.channels.filter(ch =>
                    !allChannels.find(existing => existing.id === ch.id)
                );
                allChannels = [...allChannels, ...newChannels];
            } else {
                allChannels = data.channels;
            }

            // 更新分页状态
            if (data.pagination) {
                channelsTotal = data.pagination.total;
                hasMoreChannels = data.pagination.has_more;
                if (data.pagination.has_more) {
                    channelsPage++;
                }
            }

            renderChannelList();

            if (!isLoadMore) {
                setupChannelsScrollListener();
            }

            // 加载新频道的摘要
            if (isLoadMore && newChannels.length > 0) {
                await loadChannelsSummary(newChannels.map(ch => ch.id));
            }
        }
    } catch (error) {
        console.error('加载频道列表失败:', error);
    } finally {
        isLoadingMoreChannels = false;
    }
}

// 加载指定频道的摘要
async function loadChannelsSummary(channelIds) {
    if (!channelIds || channelIds.length === 0) return;

    const user = getUser();
    if (!user || !user.id) return;

    try {
        const host = window.location.hostname;

        const response = await fetch(`${API_BASE}/api/ws/channels-summary`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                socket_id: user.id,
                channel_ids: channelIds
            })
        });

        const data = await response.json();

        if (data.success && data.channels) {

            // 只更新这些频道的未读数
            if (data.unread_counts) {
                Object.keys(data.unread_counts).forEach(chId => {
                    // 只有在当前频道列表中才更新未读数
                    if (channelIds.includes(chId)) {
                        unreadCounts[chId] = data.unread_counts[chId];
                    }
                });
            }

            // 保存频道最新消息和时间
            data.channels.forEach(ch => {
                if (ch.latest_message) {
                    channelLatestMessage[ch.id] = ch.latest_message.content;
                    channelLatestTime[ch.id] = ch.latest_message.timestamp;
                }
            });

            // 重新渲染频道列表
            renderChannelList();
        } else {
            console.warn('加载频道摘要失败:', data);
        }
    } catch (error) {
        console.error('加载频道摘要失败:', error);
    }
}

// 加载更多频道
async function loadMoreChannels() {
    if (isLoadingMoreChannels || !hasMoreChannels) return;

    isLoadingMoreChannels = true;
    await loadChannels(true);
}

// 设置频道列表滚动监听
function setupChannelsScrollListener() {
    const channelsContainer = document.getElementById('channelList');
    if (!channelsContainer) return;

    channelsContainer.addEventListener('scroll', () => {
        const scrollTop = channelsContainer.scrollTop;
        const scrollHeight = channelsContainer.scrollHeight;
        const clientHeight = channelsContainer.clientHeight;

        const scrollRatio = scrollTop / (scrollHeight - clientHeight);

        // 滚动到70%时加载更多频道（会自动加载摘要）
        if (scrollRatio > 0.7 && hasMoreChannels && !isLoadingMoreChannels) {
            loadMoreChannels();
        }
    });
}

// 启动定时刷新频道信息（每5分钟）
function startChannelsRefresh() {
    setInterval(async () => {
        await loadChannels();
    }, 5 * 60 * 1000); // 5分钟 - 微信/Telegram标准
}

// 手动刷新（下拉刷新或刷新按钮）
async function manualRefresh() {
    await loadChannels();
    await loadCategories(true); // 强制刷新标签
    await loadAllChannelsLatestMessages();
    renderChannelList();
}

// 加载标签列表（懒加载 + 定时刷新）
async function loadCategories(forceRefresh = false) {
    try {
        const host = window.location.hostname;
        const categoryType = currentTab === 'public' ? 'public' : 'private';

        // 如果已缓存且不强制刷新，直接使用缓存
        if (categoriesCache[categoryType] && !forceRefresh) {
            allCategories = categoriesCache[categoryType];
            renderCategoryButtons();
            return;
        }

        // 加载最新数据
        const response = await fetch(`${API_BASE}/api/categories?type=${categoryType}`);
        const data = await response.json();

        if (data.success && data.categories) {
            categoriesCache[categoryType] = data.categories;
            allCategories = data.categories;
            renderCategoryButtons();
        }
    } catch (error) {
        console.error('加载标签列表失败:', error);
    }
}

// 启动定时刷新标签（每10分钟）
function startCategoriesRefresh() {
    setInterval(async () => {
        const timestamp = new Date().toLocaleTimeString();

        // 并行刷新两种类型的标签
        const refreshPromises = [];

        if (categoriesCache.public) {
            refreshPromises.push(
                fetch(`${API_BASE}/api/categories?type=public`)
                    .then(res => res.json())
                    .then(data => {
                        if (data.success && data.categories) {
                            categoriesCache.public = data.categories;
                            // 如果当前在公开页面，更新显示
                            if (currentTab === 'public') {
                                allCategories = data.categories;
                                renderCategoryButtons();
                            }
                        }
                    })
                    .catch(err => console.error('公开标签刷新失败:', err))
            );
        }

        if (categoriesCache.private) {
            refreshPromises.push(
                fetch(`${API_BASE}/api/categories?type=private`)
                    .then(res => res.json())
                    .then(data => {
                        if (data.success && data.categories) {
                            categoriesCache.private = data.categories;
                            // 如果当前在私人页面，更新显示
                            if (currentTab === 'private') {
                                allCategories = data.categories;
                                renderCategoryButtons();
                            }
                        }
                    })
                    .catch(err => console.error('私人标签刷新失败:', err))
            );
        }

        await Promise.all(refreshPromises);
    }, 5 * 60 * 1000); // 5分钟 - 微信/Telegram标准
}

// 加载所有频道的最新消息摘要（支持分页）
async function loadAllChannelsLatestMessages(isLoadMore = false) {
    const host = window.location.hostname;
    const user = getUser();
    const user_id = user ? user.id : null;

    if (!user_id) {
        console.log('未登录用户，跳过加载私人频道信息');
        return;
    }

    try {
        let response;

        // 如果不是加载更多，则加载当前频道列表的摘要
        if (!isLoadMore) {
            // 获取当前频道列表的ID
            const channelIds = allChannels.map(ch => ch.id);

            if (channelIds.length === 0) {
                return;
            }

            // 使用 channel_ids 参数获取这些频道的摘要
            response = await fetch(`${API_BASE}/api/ws/channels-summary`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    socket_id: user_id,
                    channel_ids: channelIds
                })
            });
        } else {
            // 加载更多时使用分页参数
            const page = summaryPage;

            response = await fetch(`${API_BASE}/api/ws/channels-summary`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    socket_id: user_id,
                    page: page,
                    size: summaryPageSize
                })
            });
        }

        const data = await response.json();

        if (data.success && data.channels) {

            // 只更新当前频道列表的未读数
            if (data.unread_counts) {
                Object.keys(data.unread_counts).forEach(chId => {
                    // 只有在当前频道列表中才更新未读数
                    const channelId = parseInt(chId);
                    if (allChannels.find(ch => ch.id === channelId)) {
                        unreadCounts[chId] = data.unread_counts[chId];
                    }
                });
            }

            // 保存频道最新消息和时间
            data.channels.forEach(ch => {
                if (ch.latest_message) {
                    channelLatestMessage[ch.id] = ch.latest_message.content;
                    channelLatestTime[ch.id] = ch.latest_message.timestamp;
                }
            });

            // 更新分页状态（仅分页加载时）
            if (isLoadMore && data.pagination) {
                summaryTotal = data.pagination.total;
                hasMoreSummary = data.pagination.has_more;
                if (data.pagination.has_more) {
                    summaryPage++;
                }
            }

            // 渲染频道列表（更新最新消息和未读数）
            renderChannelList();
        } else {
            console.warn('加载频道摘要失败:', data);
        }
    } catch (error) {
        console.error('加载频道摘要失败:', error);
    } finally {
        isLoadingMoreSummary = false;
    }
}

// 加载更多频道摘要
async function loadMoreSummary() {
    if (isLoadingMoreSummary || !hasMoreSummary) return;

    isLoadingMoreSummary = true;
    await loadAllChannelsLatestMessages(true);
}

// 渲染标签按钮
function renderCategoryButtons() {
    const categoryMenuList = document.getElementById('categoryMenuList');
    const allBtn = document.getElementById('cat-all-btn');

    if (!categoryMenuList) return;

    // 清空容器
    categoryMenuList.innerHTML = '';

    // 将所有标签添加到下拉菜单（网格布局）
    allCategories.forEach(cat => {
        const button = document.createElement('button');
        const isSelected = currentCategory == cat.id;

        button.className = `px-3 py-2 rounded-lg text-xs font-medium transition-all duration-200 ${
            isSelected
                ? 'bg-blue-500 text-white'
                : 'hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300'
        }`;
        button.dataset.categoryId = cat.id;
        button.dataset.categoryName = cat.name;
        button.textContent = cat.name;
        button.onclick = () => {
            switchCategory(cat.id);
            hideCategoryMenu();
        };
        categoryMenuList.appendChild(button);
    });

    // 更新"全部"按钮的选中状态
    if (allBtn) {
        const isAllSelected = currentCategory === 'all' || !currentCategory;
        allBtn.className = `w-full px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-200 mb-1 ${
            isAllSelected
                ? 'bg-blue-500 text-white'
                : 'hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300'
        }`;
    }

    // 更新当前选中标签显示
    updateCategoryDisplay();
}

// 主题切换
function setupTheme() {
    // 从localStorage读取主题设置，如果没有则使用系统偏好
    const savedTheme = localStorage.getItem('theme');
    if (savedTheme) {
        isDarkMode = savedTheme === 'dark';
    } else if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
        isDarkMode = true;
    }

    applyTheme();

    // 监听系统主题变化（仅在用户没有手动设置过主题时）
    if (!savedTheme) {
        window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
            if (!localStorage.getItem('theme')) {
                isDarkMode = e.matches;
                applyTheme();
            }
        });
    }
}

function applyTheme() {
    if (isDarkMode) {
        document.documentElement.classList.add('dark');
    } else {
        document.documentElement.classList.remove('dark');
    }
}

function toggleTheme() {
    isDarkMode = !isDarkMode;
    // 保存到localStorage
    localStorage.setItem('theme', isDarkMode ? 'dark' : 'light');
    applyTheme();
}

// WebSocket 连接
function connectWebSocket() {
    const host = window.location.hostname;
    const socketUrl = `http://${host}:9080`;

    socket = io(socketUrl, {
        transports: ['websocket', 'polling']
    });

    socket.on('connect', async () => {
        updateWSStatus(true);

        // 通知服务器创建会话（传递user_id）
        const user = getUser();
        if (user && user.id) {
            try {
                await fetch(`${API_BASE}/api/ws/connect`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        socket_id: socket.id,
                        user_id: user.id
                    })
                });
            } catch (error) {
                console.error('创建会话失败:', error);
            }
        }

        // 连接成功后，重新加载频道列表（带 socket_id 获取用户权限）
        await loadChannels();
        // 自动订阅所有公开消息
        await subscribeAllChannels();
    });

    socket.on('disconnect', (reason) => {
        updateWSStatus(false);
    });

    socket.on('new_message', (message) => {
        handleNewMessage(message);
    });

    socket.on('reconnect', async () => {
        updateWSStatus(true);
        // 重连后重新订阅
        await subscribeAllChannels();
    });

    socket.on('error', (error) => {
        console.error('❌ WebSocket 错误:', error);
        updateWSStatus(false);
    });

    socket.io.on('error', (error) => {
        console.error('❌ Socket.IO 错误:', error);
    });
}

// 订阅所有公开消息
async function subscribeAllChannels() {
    if (!socket || !socket.id) {
        return;
    }

    try {
        const publicChannels = allChannels.filter(ch => ch.type === 'public');
        if (publicChannels.length === 0) {
            return;
        }

        const channelIds = publicChannels.map(ch => ch.id);

        const response = await fetch(`${API_BASE}/api/ws/subscribe`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                socket_id: socket.id,
                channel_ids: channelIds
            })
        });

        const data = await response.json();
        if (!data.success) {
            console.error('订阅失败:', data);
        }
    } catch (error) {
        console.error('订阅请求失败:', error);
    }
}

// 更新 WebSocket 状态显示
function updateWSStatus(isConnected) {
    const dot = document.getElementById('wsStatusDot');
    const text = document.getElementById('wsStatusText');

    if (!dot || !text) return;

    if (isConnected) {
        dot.className = 'w-2.5 h-2.5 rounded-full bg-green-500 shadow-lg shadow-green-500/50';
        text.textContent = '在线';
        text.className = 'text-xs text-green-600 dark:text-green-400 font-medium';
    } else {
        dot.className = 'w-2.5 h-2.5 rounded-full bg-red-500 animate-pulse';
        text.textContent = '离线';
        text.className = 'text-xs text-red-600 dark:text-red-400 font-medium';
    }
}

// 格式化消息时间（飞书风格）
function formatMessageTime(timestamp) {
    if (!timestamp) return '';

    let msgDate;
    // 处理不同格式的时间戳
    if (typeof timestamp === 'number') {
        // 如果是毫秒时间戳
        if (timestamp > 1000000000000) {
            msgDate = new Date(timestamp);
        } else {
            // 如果是秒时间戳，转换为毫秒
            msgDate = new Date(timestamp * 1000);
        }
    } else if (typeof timestamp === 'string') {
        // 如果是字符串，尝试解析
        msgDate = new Date(timestamp);
    } else {
        return '';
    }

    // 检查日期是否有效
    if (isNaN(msgDate.getTime())) {
        console.error('无效的时间戳:', timestamp);
        return '';
    }

    const now = new Date();

    // 更准确的方法：直接比较本地日期（不考虑时间）
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const messageDay = new Date(msgDate.getFullYear(), msgDate.getMonth(), msgDate.getDate());
    const dayDiff = Math.round((today - messageDay) / (1000 * 60 * 60 * 24));

    // 今天：显示时间 20:11
    if (dayDiff === 0) {
        const hours = msgDate.getHours().toString().padStart(2, '0');
        const minutes = msgDate.getMinutes().toString().padStart(2, '0');
        return `${hours}:${minutes}`;
    }
    // 昨天：显示"昨天"
    else if (dayDiff === 1) {
        return '昨天';
    }
    // 今年：显示月日 1月20日
    else if (msgDate.getFullYear() === now.getFullYear()) {
        return `${msgDate.getMonth() + 1}月${msgDate.getDate()}日`;
    }
    // 去年及更早：显示完整日期 2011年1月20日
    else {
        return `${msgDate.getFullYear()}年${msgDate.getMonth() + 1}月${msgDate.getDate()}日`;
    }
}

// 渲染频道列表
function renderChannelList() {
    try {
        const container = document.getElementById('channelList');

        // 根据当前标签筛选频道
        let channels;
        if (currentTab === 'private') {
            // 私人订阅：type='private'
            channels = allChannels.filter(ch => ch.type === 'private');
        } else if (currentTab === 'public') {
            // 公开消息：type='public'
            channels = allChannels.filter(ch => ch.type === 'public');

            // 如果选择了特定分类，进一步筛选
            if (currentCategory && currentCategory !== 'all') {
                channels = channels.filter(ch => ch.category === currentCategory);
            }
        }

        if (!channels || channels.length === 0) {
            container.innerHTML = `
                <div class="text-center text-gray-400 py-8">
                    <i class="fas fa-inbox text-4xl mb-2"></i>
                    <p>暂无频道</p>
                </div>
            `;
            return;
        }

        // 后端已按最新消息时间排序，无需前端重复排序

        container.innerHTML = channels.map(channel => {
            return renderChannelItem(channel);
        }).join('');
    } catch (error) {
        console.error('渲染频道列表失败:', error);
        const container = document.getElementById('channelList');
        if (container) {
            container.innerHTML = `
                <div class="text-center text-gray-400 py-8">
                    <i class="fas fa-exclamation-triangle text-4xl mb-2"></i>
                    <p>加载失败，请刷新页面</p>
                </div>
            `;
        }
    }
}

// 渲染单个频道项（统一复用函数）
function renderChannelItem(channel) {
    const unread = unreadCounts[channel.id] || 0;
    const latestMsg = channelLatestMessage[channel.id];
    const latestTime = channelLatestTime[channel.id];
    const formattedTime = latestTime ? formatMessageTime(latestTime) : '';

    // 头像处理：如果有头像URL，显示头像；否则显示首字
    let avatarHtml;
    if (channel.avatar) {
        avatarHtml = `<img src="${channel.avatar}" class="w-10 h-10 rounded-full object-cover" alt="${channel.name}">`;
    } else {
        // 取频道名称的第一个字符作为默认头像
        const firstChar = channel.name ? channel.name.charAt(0).toUpperCase() : '?';
        avatarHtml = `<div class="w-10 h-10 rounded-full bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center text-white font-bold">${firstChar}</div>`;
    }

    return `
        <div class="channel-item flex items-center gap-3 p-3 rounded-lg cursor-pointer transition-all hover:bg-gray-100 dark:hover:bg-gray-700 ${currentChannel === channel.id ? 'bg-blue-50 dark:bg-blue-900/30' : ''}"
             onclick="selectChannel('${channel.id}')">
            <div class="relative flex-shrink-0">
                ${avatarHtml}
                ${unread > 0 ? `
                    <span class="absolute -top-0.5 -right-0.5 min-w-[1rem] h-4 px-1 bg-red-500 text-white text-[9px] font-medium rounded-full flex items-center justify-center">
                        ${unread > 99 ? '99+' : unread}
                    </span>
                ` : ''}
            </div>
            <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2">
                    <p class="font-medium truncate flex-1">${channel.name}</p>
                    ${formattedTime ? `<span class="text-xs text-gray-400 flex-shrink-0">${formattedTime}</span>` : ''}
                </div>
                ${latestMsg && latestMsg.trim() ? `<p class="text-xs text-gray-500 truncate">${latestMsg}</p>` : ''}
            </div>
        </div>
    `;
}

// 切换标签页
async function switchTab(tab) {
    // 切换到私人订阅时检查登录
    if (tab === 'private') {
        const token = localStorage.getItem('token');
        if (!token) {
            // 未登录，直接跳转登录页
            window.location.href = 'auth.html';
            return;
        }
    }

    currentTab = tab;
    // 重置分类选择
    if (tab === 'private') {
        currentCategory = null;
    } else {
        currentCategory = 'all';
    }

    // 更新按钮样式
    updateTabButtons();

    // 重新加载标签列表（公开/私人分开）
    loadCategories();

    // 重置分页状态并重新加载频道列表
    channelsPage = 1;
    channelsTotal = 0;
    hasMoreChannels = false;
    allChannels = [];
    await loadChannels();

    // 清空未读数（切换tab时重新加载）
    unreadCounts = {};

    // 重置摘要分页状态并重新加载摘要
    summaryPage = 1;
    summaryTotal = 0;
    hasMoreSummary = false;
    await loadAllChannelsLatestMessages();

    // 重新渲染频道列表
    currentChannel = null;
    clearMessages();

    // 切换Tab时滚动回到顶部
    const channelsContainer = document.getElementById('channelList');
    if (channelsContainer) {
        channelsContainer.scrollTop = 0;
    }
}

// 更新标签按钮样式
function updateTabButtons() {
    const tab = currentTab;
    const privateBtn = document.getElementById('tab-private');
    const publicBtn = document.getElementById('tab-public');

    if (privateBtn) {
        privateBtn.className = tab === 'private'
            ? 'flex-1 py-2 px-3 rounded-lg text-sm font-medium transition-colors bg-blue-500 text-white'
            : 'flex-1 py-2 px-3 rounded-lg text-sm font-medium transition-colors hover:bg-gray-100 dark:hover:bg-gray-700';
    }

    if (publicBtn) {
        publicBtn.className = tab === 'public'
            ? 'flex-1 py-2 px-3 rounded-lg text-sm font-medium transition-colors bg-blue-500 text-white'
            : 'flex-1 py-2 px-3 rounded-lg text-sm font-medium transition-colors hover:bg-gray-100 dark:hover:bg-gray-700';
    }
}

// 切换分类标签
function switchCategory(category) {
    currentCategory = category;

    // 更新按钮显示（包括下拉菜单中的选中状态）
    renderCategoryButtons();

    // 重新渲染频道列表
    currentChannel = null;
    renderChannelList();
    clearMessages();
}

// 切换分类下拉菜单
function toggleCategoryMenu() {
    const menu = document.getElementById('categoryMenu');
    const arrow = document.getElementById('dropdownArrow');

    if (menu) {
        const isHidden = menu.classList.contains('hidden');
        menu.classList.toggle('hidden');

        // 旋转箭头图标
        if (arrow) {
            arrow.style.transform = isHidden ? 'rotate(180deg)' : 'rotate(0deg)';
        }

        // 展开时更新按钮状态
        if (isHidden) {
            renderCategoryButtons();
        }
    }
}

// 隐藏下拉菜单
function hideCategoryMenu() {
    const menu = document.getElementById('categoryMenu');
    const arrow = document.getElementById('dropdownArrow');

    if (menu) {
        menu.classList.add('hidden');
        // 恢复箭头图标
        if (arrow) {
            arrow.style.transform = 'rotate(0deg)';
        }
    }
}

// 更新当前选中标签的显示
function updateCategoryDisplay() {
    const label = document.getElementById('currentCategoryLabel');
    const dropdownBtn = document.getElementById('currentCategoryBtn');
    const dropdownArrow = document.getElementById('dropdownArrow');

    if (!label || !dropdownBtn) return;

    if (currentCategory && currentCategory !== 'all') {
        // 显示选中的标签名称
        const selectedCategory = allCategories.find(cat => cat.id == currentCategory);
        if (selectedCategory) {
            label.textContent = selectedCategory.name;
        } else {
            // 未找到对应的标签
            label.textContent = '全部';
        }
    } else {
        // 默认状态：显示"全部"
        label.textContent = '全部';
    }

    // 主按钮始终显示灰色（不显示蓝色背景）
    dropdownBtn.className = 'w-full px-3 py-2 rounded-lg text-sm font-medium transition-all duration-200 bg-gray-100 hover:bg-gray-200 dark:bg-gray-800 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300 flex items-center justify-between gap-2 cursor-pointer border border-gray-300 dark:border-gray-600';

    // 旋转箭头
    if (dropdownArrow) {
        const isMenuOpen = document.getElementById('categoryMenu')?.classList.contains('hidden') === false;
        dropdownArrow.style.transform = isMenuOpen ? 'rotate(180deg)' : 'rotate(0deg)';
    }
}

// 点击外部关闭下拉菜单
document.addEventListener('click', function(event) {
    const dropdown = document.getElementById('categoryDropdown');
    const menu = document.getElementById('categoryMenu');
    const dropdownBtn = document.getElementById('currentCategoryBtn');

    // 如果点击的不是下拉区域，关闭菜单
    if (dropdown && menu && dropdownBtn &&
        !dropdown.contains(event.target) &&
        !menu.contains(event.target) &&
        !dropdownBtn.contains(event.target)) {
        hideCategoryMenu();
    }
});

// 选择频道
async function selectChannel(channelId) {
    // 检查登录状态
    const token = localStorage.getItem('token');
    if (!token) {
        // 未登录，直接跳转登录页
        window.location.href = 'auth.html';
        return;
    }

    currentChannel = channelId;

    // 立即清除本地未读数（快速响应）
    if (unreadCounts[channelId]) {
        unreadCounts[channelId] = 0;
    }

    // 无论是否有未读数，都更新UI以显示正确的选中状态
    renderChannelList();

    // 通知后端清除未读数
    try {
        const host = window.location.hostname;
        const user = getUser();
        if (user && user.id) {
            await fetch(`${API_BASE}/api/ws/mark-read`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    socket_id: user.id,
                    channel_id: channelId
                })
            });
        }
    } catch (error) {
        console.error('标记已读失败:', error);
    }

    // 从 allChannels 中查找频道
    const channel = allChannels.find(c => c.id === channelId);

    if (channel) {
        document.getElementById('channelTitle').textContent = channel.name;

        // 检查缓存，有缓存直接显示，没有才加载
        if (loadedChannels.has(channelId) && channelMessagesCache[channelId]) {
            renderMessagesFromCache(channelId);
        } else {
            loadMessages(channelId, true); // true 表示初始加载
        }

        // 加载豆包AI总结
        loadDoubaiSummary(channelId);
    }
}

// 从缓存渲染消息
function renderMessagesFromCache(channelId) {
    const container = document.getElementById('messageContainer');
    const cache = channelMessagesCache[channelId];

    if (!cache || !cache.messages || cache.messages.length === 0) {
        container.innerHTML = `
            <div class="text-center text-gray-400 py-8">
                <i class="fas fa-comment-dots text-4xl mb-2"></i>
                <p>暂无消息</p>
            </div>
        `;
        return;
    }

    // 直接从缓存渲染（不需要loading，不需要滚动动画，瞬间显示）
    let messagesHTML = '';
    cache.messages.forEach((msg, index) => {
        const prevMsg = index > 0 ? cache.messages[index - 1] : null;
        // 使用后端返回的show_date_separator字段
        const showDateSep = msg.show_date_separator || false;
        messagesHTML += createMessageHTML(msg, prevMsg, showDateSep);
    });
    container.innerHTML = messagesHTML;

    // 使用 requestAnimationFrame 确保DOM渲染完成后再滚动
    // 图片已预留 min-height 200px，不会导致布局跳动
    requestAnimationFrame(() => {
        container.scrollTop = container.scrollHeight;
    });

    // 更新分页信息
    channelMessageOffset[channelId] = cache.offset;
    channelMessageTotal[channelId] = cache.total;
}

// 加载消息
async function loadMessages(channelId, isInitial = false, limit = 30) {
    const container = document.getElementById('messageContainer');

    // 初始加载显示加载中
    if (isInitial) {
        container.innerHTML = `
            <div class="text-center text-gray-400 py-8">
                <i class="fas fa-spinner fa-spin text-4xl mb-2"></i>
                <p>加载中...</p>
            </div>
        `;
        // 重置分页信息
        channelMessageOffset[channelId] = 0;
        channelMessageTotal[channelId] = 0;
    }

    // 记录当前滚动位置（用于加载更多后保持）
    const oldScrollHeight = container.scrollHeight;
    const oldScrollTop = container.scrollTop;

    // 获取容器中第一条消息的时间戳（用于避免重复日期分割线）
    let lastLoadedTimestamp = null;
    if (!isInitial && channelMessagesCache[channelId] && channelMessagesCache[channelId].messages.length > 0) {
        // 获取缓存中第一条消息（最早的消息）的时间戳
        lastLoadedTimestamp = channelMessagesCache[channelId].messages[0].timestamp;
    }

    try {
        const host = window.location.hostname;
        const user = getUser(); // 获取当前登录用户
        const user_id = user ? user.id : null;
        const offset = channelMessageOffset[channelId] || 0;

        const response = await fetch(`${API_BASE}/api/ws/switch-channel`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                socket_id: user_id || 'guest',
                channel_id: channelId,
                limit: limit,
                offset: offset,
                last_loaded_timestamp: lastLoadedTimestamp
            })
        });

        const data = await response.json();

        if (data.success) {
            // 保存分页信息
            const pagination = data.pagination || {};
            channelMessageTotal[channelId] = pagination.total || 0;

            if (data.history.length === 0 && isInitial) {
                container.innerHTML = `
                    <div class="text-center text-gray-400 py-8">
                        <i class="fas fa-comment-dots text-4xl mb-2"></i>
                        <p>暂无消息</p>
                    </div>
                `;
                // 保存空缓存
                channelMessagesCache[channelId] = {
                    messages: [],
                    offset: 0,
                    total: 0
                };
                loadedChannels.add(channelId);
                return;
            }

            if (data.history.length > 0) {
                // 构建消息HTML，使用后端返回的show_date_separator标记
                let newMessagesHTML = '';
                data.history.forEach((msg, index) => {
                    const prevMsg = index > 0 ? data.history[index - 1] : null;
                    // 直接使用后端计算的show_date_separator字段
                    newMessagesHTML += createMessageHTML(msg, prevMsg, msg.show_date_separator);
                });

                if (isInitial) {
                    // 大厂做法：先隐藏容器，插入内容，再滚动显示
                    // 图片已预留 min-height 200px，不会导致布局跳动

                    // 1. 先隐藏容器（使用opacity淡入效果）
                    container.style.opacity = '0';

                    // 2. 插入内容
                    container.innerHTML = newMessagesHTML;

                    // 3. 使用 requestAnimationFrame 确保 DOM 渲染完成
                    requestAnimationFrame(() => {
                        requestAnimationFrame(() => {
                            // 4. 设置滚动到底部
                            container.scrollTop = container.scrollHeight;

                            // 5. 显示容器（淡入效果）
                            container.style.transition = 'opacity 0.15s ease-in';
                            container.style.opacity = '1';
                        });
                    });

                    // 保存到缓存
                    channelMessagesCache[channelId] = {
                        messages: data.history,
                        offset: data.history.length,
                        total: pagination.total || 0
                    };
                    loadedChannels.add(channelId);

                } else {
                    // 加载更多：插入到顶部
                    const oldHeight = container.scrollHeight;

                    // 先记录插入前的第一条元素
                    const firstChild = container.firstElementChild;

                    container.insertAdjacentHTML('afterbegin', newMessagesHTML);

                    // 计算新增加的高度
                    const newHeight = container.scrollHeight;
                    const heightDiff = newHeight - oldHeight;

                    // 恢复滚动位置（加上新增的高度）
                    container.scrollTop = oldScrollTop + heightDiff;

                    // 更新缓存（将新消息添加到缓存前面）
                    if (channelMessagesCache[channelId]) {
                        channelMessagesCache[channelId].messages = [
                            ...data.history,
                            ...channelMessagesCache[channelId].messages
                        ];
                        channelMessagesCache[channelId].offset += data.history.length;
                    }
                }

                // 更新已加载数量
                channelMessageOffset[channelId] = (channelMessageOffset[channelId] || 0) + data.history.length;

                // 更新最新消息缓存（只更新一次，避免覆盖）
                if (isInitial || !channelLatestMessage[channelId]) {
                    // 数据库返回的消息是"旧消息在前，新消息在后"，所以取最后一条
                    const latestMsg = data.history[data.history.length - 1];
                    // 提取纯文本内容
                    let msgText = latestMsg.content || '';
                    // 去除 HTML 标签
                    msgText = msgText.replace(/<[^>]*>/g, '');
                    // Markdown图片格式替换为 [图片] 文本
                    msgText = msgText.replace(/!\[([^\]]*)\]\([^)]+\)/g, '[图片]');
                    // 截断到 30 个字符
                    if (msgText.length > 30) {
                        msgText = msgText.substring(0, 30) + '...';
                    }
                    channelLatestMessage[channelId] = msgText;
                    // 保存消息时间
                    channelLatestTime[channelId] = latestMsg.timestamp;
                }
            }

            // 合并更新未读数（保留实时推送的未读数）
            if (data.unread_counts) {
                Object.keys(data.unread_counts).forEach(chId => {
                    // 只有当服务器的未读数大于本地时才更新
                    if (!unreadCounts[chId] || data.unread_counts[chId] > unreadCounts[chId]) {
                        unreadCounts[chId] = data.unread_counts[chId];
                    }
                });
            }
            // 当前频道的未读数已经在 selectChannel 中清零了
            renderChannelList();
        }
    } catch (error) {
        console.error('加载消息失败:', error);
        if (isInitial) {
            container.innerHTML = `
                <div class="text-center text-red-400 py-8">
                    <i class="fas fa-exclamation-circle text-4xl mb-2"></i>
                    <p>加载失败，请重试</p>
                </div>
            `;
            container.style.opacity = '1';
        }
    } finally {
        isLoadingMore = false;
    }
}

// 加载更多历史消息
async function loadMoreMessages() {
    if (!currentChannel || isLoadingMore) return;

    const offset = channelMessageOffset[currentChannel] || 0;
    const total = channelMessageTotal[currentChannel] || 0;

    // 检查是否还有更多消息
    if (offset >= total) {
        return;
    }

    isLoadingMore = true;

    // 在顶部显示加载提示
    const container = document.getElementById('messageContainer');
    const loadingDiv = document.createElement('div');
    loadingDiv.id = 'loading-more';
    loadingDiv.className = 'text-center text-gray-400 py-4';
    loadingDiv.innerHTML = '<i class="fas fa-spinner fa-spin mr-2"></i>加载历史消息...';
    container.insertAdjacentElement('afterbegin', loadingDiv);

    // 加载更多消息（30条）
    await loadMessages(currentChannel, false, 30);

    // 移除加载提示
    const loadingEl = document.getElementById('loading-more');
    if (loadingEl) loadingEl.remove();
}

// 创建消息HTML
function createMessageHTML(message, prevMessage = null, showDateSeparator = false) {
    const readClass = message.read ? 'opacity-60' : '';

    // 判断是否显示时间（间隔 > 2分钟）
    const showTime = shouldShowTime(message, prevMessage);

    // 悬停时间：只显示时分
    const hoverTime = formatMessageTimeOnly(message.timestamp);

    // 完整时间（用于第一条或跨日期消息）
    const fullTime = formatMessageTimeDetail(message.timestamp);

    // 固定显示时间：根据是否跨日期决定格式
    let displayTime = '';
    if (showTime) {
        if (showDateSeparator || !prevMessage) {
            // 第一条或跨日期：显示完整时间（昨天23:00、2月1日22:22等）
            displayTime = fullTime;
        } else {
            // 同一天内：只显示时分（21:35）
            displayTime = hoverTime;
        }
    }

    let content = message.content;

    // 将Markdown图片格式 ![alt](url) 替换为 <img> 标签
    // 匹配格式：![任意文本](任意URL)
    content = content.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, '<img src="$2" alt="$1" class="w-full h-auto rounded max-w-full object-contain" loading="lazy" />');

    // 处理其他Markdown语法
    if (typeof marked !== 'undefined') {
        content = marked.parse(content);
    }

    // 标题（如果有）
    const titleHTML = message.title
        ? `<h4 class="font-semibold text-gray-900 dark:text-white mb-2">${message.title}</h4>`
        : '';

    // 所有消息都添加悬停时间属性（只有时分）
    const dataAttr = `data-full-time="${hoverTime}"`;

    // 日期分割线（跨日期时显示，带水平线）
    const dateSeparatorHTML = showDateSeparator
        ? `<div class="date-separator"><span>${formatDateSeparator(message.timestamp)}</span></div>`
        : '';

    // 同一天内的时间标签（间隔>2分钟，居中，不带分割线）
    const timeLabelHTML = showTime && !showDateSeparator
        ? `<div class="time-label"><span>${displayTime}</span></div>`
        : '';

    return `
        ${dateSeparatorHTML}
        ${timeLabelHTML}
        <div class="message-item-wrapper ${readClass}" ${dataAttr}>
            <div class="message-box bg-white dark:bg-dark-surface rounded-lg p-4 shadow-sm border border-gray-200 dark:border-gray-700 overflow-hidden">
                ${titleHTML}
                <div class="message-content text-gray-700 dark:text-gray-300 overflow-hidden">${content}</div>
            </div>
        </div>
    `;
}

// 图片点击放大预览
function setupImageViewer() {
    // 检查是否已经创建过
    if (document.getElementById('imageViewer')) {
        return;
    }

    // 创建图片查看器模态框
    const viewer = document.createElement('div');
    viewer.id = 'imageViewer';
    viewer.style.cssText = 'display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.9); z-index: 50; align-items: center; justify-content: center;';
    viewer.innerHTML = `
        <div style="position: relative; max-width: 90vw; max-height: 90vh;">
            <img id="viewerImage" src="" style="max-width: 90vw; max-height: 90vh; object-fit: contain;" />
            <button id="closeViewer" style="position: absolute; top: 16px; right: 16px; color: white; font-size: 32px; background: rgba(0,0,0,0.5); width: 40px; height: 40px; border-radius: 50%; cursor: pointer; border: 2px solid white; display: flex; align-items: center; justify-content: center; line-height: 1;">&times;</button>
        </div>
    `;

    // 点击背景关闭
    viewer.onclick = (e) => {
        if (e.target === viewer) {
            closeViewer();
        }
    };

    // 点击关闭按钮
    const closeBtn = viewer.querySelector('#closeViewer');
    if (closeBtn) {
        closeBtn.onclick = (e) => {
            e.stopPropagation();
            closeViewer();
        };
    }

    // ESC 键关闭
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            const viewer = document.getElementById('imageViewer');
            if (viewer && viewer.style.display !== 'none') {
                closeViewer();
            }
        }
    });

    document.body.appendChild(viewer);

    // 关闭函数
    function closeViewer() {
        viewer.style.display = 'none';
    }

    // 打开函数
    function openViewer(src) {
        const viewerImg = document.getElementById('viewerImage');
        viewerImg.src = src;
        viewer.style.display = 'flex';
    }

    // 为每张图片添加放大镜图标覆盖层
    const addZoomIcon = (img) => {
        if (img.dataset.zoomIcon) return; // 已添加过

        const wrapper = document.createElement('div');
        wrapper.className = 'relative inline-block';
        wrapper.style.cssText = 'display: inline-block;';

        img.parentNode.insertBefore(wrapper, img);
        wrapper.appendChild(img);

        // 创建放大镜图标
        const zoomIcon = document.createElement('div');
        zoomIcon.className = 'absolute inset-0 flex items-center justify-center pointer-events-none opacity-0 transition-opacity duration-200';
        zoomIcon.innerHTML = `
            <div class="bg-black/50 rounded-full w-12 h-12 flex items-center justify-center">
                <svg class="w-6 h-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0zM10 7v6m3-3H7"></path>
                </svg>
            </div>
        `;

        wrapper.appendChild(zoomIcon);
        img.dataset.zoomIcon = 'true';

        // 悬停显示放大镜
        wrapper.addEventListener('mouseenter', () => {
            zoomIcon.classList.remove('opacity-0');
            zoomIcon.classList.add('opacity-100');
        });

        wrapper.addEventListener('mouseleave', () => {
            zoomIcon.classList.add('opacity-0');
            zoomIcon.classList.remove('opacity-100');
        });
    };

    // 监听消息容器中的图片
    const observer = new MutationObserver((mutations) => {
        mutations.forEach(mutation => {
            mutation.addedNodes.forEach(node => {
                if (node.nodeType === 1) {
                    const images = node.tagName === 'IMG' ? [node] : node.querySelectorAll('.message-content img');
                    images.forEach(addZoomIcon);
                }
            });
        });
    });

    const messageContainer = document.getElementById('messageContainer');
    if (messageContainer) {
        observer.observe(messageContainer, { childList: true, subtree: true });
    }

    // 监听图片点击
    document.body.addEventListener('click', (e) => {
        const img = e.target.closest('.message-content img');
        if (img) {
            openViewer(img.src);
        }
    });
}

// 格式化详细消息时间（包含完整日期）
function formatMessageTimeDetail(timestamp) {
    if (!timestamp) return '';

    let msgDate;
    if (typeof timestamp === 'number') {
        if (timestamp > 1000000000000) {
            msgDate = new Date(timestamp);
        } else {
            msgDate = new Date(timestamp * 1000);
        }
    } else if (typeof timestamp === 'string') {
        msgDate = new Date(timestamp);
    } else {
        return '';
    }

    if (isNaN(msgDate.getTime())) {
        console.error('无效的时间戳:', timestamp);
        return '';
    }

    const now = new Date();

    // 修复：正确比较日期（只比较年月日，忽略时间）
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const messageDay = new Date(msgDate.getFullYear(), msgDate.getMonth(), msgDate.getDate());
    const dayDiff = Math.round((today - messageDay) / (1000 * 60 * 60 * 24));

    // 格式化时间 HH:mm
    const hours = msgDate.getHours().toString().padStart(2, '0');
    const minutes = msgDate.getMinutes().toString().padStart(2, '0');
    const timeStr = `${hours}:${minutes}`;

    // 今天：只显示时间
    if (dayDiff === 0) {
        return timeStr;
    }
    // 昨天：显示昨天 + 时间
    else if (dayDiff === 1) {
        return `昨天 ${timeStr}`;
    }
    // 今年：显示月日 + 时间
    else if (msgDate.getFullYear() === now.getFullYear()) {
        return `${msgDate.getMonth() + 1}月${msgDate.getDate()}日 ${timeStr}`;
    }
    // 去年及更早：显示完整日期 + 时间
    else {
        return `${msgDate.getFullYear()}年${msgDate.getMonth() + 1}月${msgDate.getDate()}日 ${timeStr}`;
    }
}

// 只显示时分（用于悬停和同一天内的消息）
function formatMessageTimeOnly(timestamp) {
    if (!timestamp) return '';

    let msgDate;
    if (typeof timestamp === 'number') {
        if (timestamp > 1000000000000) {
            msgDate = new Date(timestamp);
        } else {
            msgDate = new Date(timestamp * 1000);
        }
    } else if (typeof timestamp === 'string') {
        msgDate = new Date(timestamp);
    } else {
        return '';
    }

    if (isNaN(msgDate.getTime())) {
        console.error('无效的时间戳:', timestamp);
        return '';
    }

    const hours = msgDate.getHours().toString().padStart(2, '0');
    const minutes = msgDate.getMinutes().toString().padStart(2, '0');
    return `${hours}:${minutes}`;
}

// 简化版时间格式化（飞书风格：同一天只显示时分）
function formatMessageTimeSimple(timestamp, prevMessage) {
    if (!timestamp) return '';

    let msgDate;
    if (typeof timestamp === 'number') {
        if (timestamp > 1000000000000) {
            msgDate = new Date(timestamp);
        } else {
            msgDate = new Date(timestamp * 1000);
        }
    } else if (typeof timestamp === 'string') {
        msgDate = new Date(timestamp);
    } else {
        return '';
    }

    if (isNaN(msgDate.getTime())) {
        console.error('无效的时间戳:', timestamp);
        return '';
    }

    const hours = msgDate.getHours().toString().padStart(2, '0');
    const minutes = msgDate.getMinutes().toString().padStart(2, '0');
    const timeStr = `${hours}:${minutes}`;

    // 如果没有前一条消息，显示完整时间
    if (!prevMessage) {
        return formatMessageTimeDetail(timestamp);
    }

    // 比较日期是否相同
    const prevDate = new Date(prevMessage.timestamp);
    const isSameDay = msgDate.getFullYear() === prevDate.getFullYear() &&
                      msgDate.getMonth() === prevDate.getMonth() &&
                      msgDate.getDate() === prevDate.getDate();

    // 同一天只显示时分
    if (isSameDay) {
        return timeStr;
    } else {
        // 不同天显示完整日期
        return formatMessageTimeDetail(timestamp);
    }
}

// 判断是否应该显示时间（间隔 > 2分钟）
function shouldShowTime(currentMsg, prevMsg) {
    if (!prevMsg) return true; // 第一条消息总是显示时间

    const currentTime = new Date(currentMsg.timestamp).getTime();
    const prevTime = new Date(prevMsg.timestamp).getTime();
    const timeDiff = (currentTime - prevTime) / 1000 / 60; // 转换为分钟

    return timeDiff > 2; // 间隔超过2分钟才显示时间
}

// 判断是否应该显示日期分隔线
function shouldShowDateSeparator(currentMsg, prevMsg) {
    if (!prevMsg) return true; // 第一条消息总是显示日期

    const currentDate = new Date(currentMsg.timestamp);
    const prevDate = new Date(prevMsg.timestamp);

    // 比较年月日是否不同
    return currentDate.getFullYear() !== prevDate.getFullYear() ||
           currentDate.getMonth() !== prevDate.getMonth() ||
           currentDate.getDate() !== prevDate.getDate();
}

// 格式化日期分隔线文本
function formatDateSeparator(timestamp) {
    const msgDate = new Date(timestamp);
    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const messageDay = new Date(msgDate.getFullYear(), msgDate.getMonth(), msgDate.getDate());
    const dayDiff = Math.round((today - messageDay) / (1000 * 60 * 60 * 24));

    const hours = msgDate.getHours().toString().padStart(2, '0');
    const minutes = msgDate.getMinutes().toString().padStart(2, '0');
    const timeStr = `${hours}:${minutes}`;

    if (dayDiff === 0) {
        return `今天 ${timeStr}`;
    } else if (dayDiff === 1) {
        return `昨天 ${timeStr}`;
    } else if (msgDate.getFullYear() === now.getFullYear()) {
        return `${msgDate.getMonth() + 1}月${msgDate.getDate()}日 ${timeStr}`;
    } else {
        return `${msgDate.getFullYear()}年${msgDate.getMonth() + 1}月${msgDate.getDate()}日 ${timeStr}`;
    }
}

// 清空消息区
function clearMessages() {
    document.getElementById('messageContainer').innerHTML = `
        <div class="flex items-center justify-center h-full text-gray-400">
            <div class="text-center">
                <i class="fas fa-comment-dots text-6xl mb-4"></i>
                <p>请选择左侧频道开始查看消息</p>
            </div>
        </div>
    `;
    document.getElementById('channelTitle').textContent = '请选择频道';
}

// 动态加载频道并插入到列表顶部（用于未加载频道收到新消息时）
async function loadChannelAndInsert(channelId) {
    const host = window.location.hostname;

    try {
        // 从 allChannels 中查找该频道
        const existingChannel = allChannels.find(ch => ch.id === channelId);
        if (existingChannel) {
            // 频道已存在，移到最前面
            allChannels = allChannels.filter(ch => ch.id !== channelId);
            allChannels.unshift(existingChannel);
            renderChannelList();
            return;
        }

        // 从后端获取该频道的详细信息
        const user = getUser();
        const socketId = user ? user.id : null;

        const url = `${API_BASE}/api/channels/${channelId}${socketId ? `?socket_id=${socketId}` : ''}`;
        const response = await fetch(url);

        if (!response.ok) {
            console.error(`获取频道${channelId}信息失败`);
            return;
        }

        const data = await response.json();
        if (data.success && data.channel) {
            // 插入到列表最前面
            allChannels.unshift(data.channel);

            // 重新渲染频道列表
            renderChannelList();
        }
    } catch (error) {
        console.error('动态加载频道失败:', error);
    }
}

// 处理新消息
function handleNewMessage(message) {
    // 检查频道是否在当前列表中
    const channelInList = allChannels.find(ch => ch.id === message.channel_id);

    // 如果频道不在列表中（第21-200个频道），动态加载并插入
    if (!channelInList) {
        loadChannelAndInsert(message.channel_id);
    }

    // 更新最新消息缓存
    if (message.channel_id && message.content) {
        let msgText = message.content;
        // 去除HTML标签
        msgText = msgText.replace(/<[^>]*>/g, '');
        // Markdown图片格式替换为 [图片] 文本
        msgText = msgText.replace(/!\[([^\]]*)\]\([^)]+\)/g, '[图片]');
        // 截断长度
        if (msgText.length > 30) {
            msgText = msgText.substring(0, 30) + '...';
        }
        channelLatestMessage[message.channel_id] = msgText;

        if (message.timestamp) {
            channelLatestTime[message.channel_id] = message.timestamp;
        }
    }

    // 更新未读数（只有不是当前频道时才增加）
    if (message.channel_id && message.channel_id !== currentChannel) {
        if (!unreadCounts[message.channel_id]) {
            unreadCounts[message.channel_id] = 0;
        }
        unreadCounts[message.channel_id]++;
    }

    // 更新缓存（如果频道已加载）
    if (loadedChannels.has(message.channel_id) && channelMessagesCache[message.channel_id]) {
        channelMessagesCache[message.channel_id].messages.push(message);
        channelMessagesCache[message.channel_id].total++;
    }

    // 如果当前正好在这个频道，直接显示消息
    if (message.channel_id === currentChannel) {
        const container = document.getElementById('messageContainer');

        // 获取前一条消息（从缓存或当前容器的最后一条消息）
        let prevMsg = null;
        if (channelMessagesCache[message.channel_id] &&
            channelMessagesCache[message.channel_id].messages.length > 0) {
            const messages = channelMessagesCache[message.channel_id].messages;
            prevMsg = messages[messages.length - 1];
        }

        // 新消息：后端没有计算show_date_separator，前端需要判断
        const showDateSep = shouldShowDateSeparator(message, prevMsg);
        const msgHTML = createMessageHTML(message, prevMsg, showDateSep);

        const isAtBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 50;

        container.insertAdjacentHTML('beforeend', msgHTML);

        if (isAtBottom) {
            requestAnimationFrame(() => {
                container.scrollTop = container.scrollHeight;
            });
        }
    }

    // 将该频道移到列表顶部（新消息排最前）
    const channelIndex = allChannels.findIndex(ch => ch.id === message.channel_id);
    if (channelIndex > 0) {
        const [channel] = allChannels.splice(channelIndex, 1);
        allChannels.unshift(channel);
    }

    // 更新频道列表显示（未读数和最新消息）
    renderChannelList();
}

// 搜索功能
function handleSearch(query) {
    if (!query) {
        renderChannelList();
        return;
    }

    // 根据当前标签筛选频道
    let channels;
    if (currentTab === 'private') {
        channels = allChannels.filter(ch => ch.type === 'private');
    } else if (currentTab === 'public') {
        channels = allChannels.filter(ch => ch.type === 'public');

        // 如果选择了特定分类，进一步筛选
        if (currentCategory && currentCategory !== 'all') {
            channels = channels.filter(ch => ch.category === currentCategory);
        }
    }

    const filtered = channels.filter(c =>
        c.name.toLowerCase().includes(query.toLowerCase())
    );

    const container = document.getElementById('channelList');

    if (filtered.length === 0) {
        container.innerHTML = `
            <div class="text-center text-gray-400 py-8">
                <i class="fas fa-search text-4xl mb-2"></i>
                <p>未找到 "${query}"</p>
            </div>
        `;
    } else {
        // 按最新消息时间排序（有最新消息的排前面）
        filtered.sort((a, b) => {
            const timeA = channelLatestTime[a.id] || 0;
            const timeB = channelLatestTime[b.id] || 0;
            return timeB - timeA; // 降序，最新的在前
        });

        // 使用统一的渲染函数
        container.innerHTML = filtered.map(channel => {
            return renderChannelItem(channel);
        }).join('');
    }
}

// 弹窗控制
function showAuthModal() {
    const modal = document.getElementById('authModal');
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    // 默认显示卡密兑换标签页
    switchAuthTab('card');
}

function closeAuthModal() {
    const modal = document.getElementById('authModal');
    modal.classList.add('hidden');
    modal.classList.remove('flex');
}

// ==================== 卡密兑换功能 ====================

let currentCardData = null; // 存储当前验证的卡密数据
let selectedChannelIds = []; // 选中的频道ID列表

// 切换授权标签页
function switchAuthTab(tab) {
    const cardTabBtn = document.getElementById('cardTabBtn');
    const subscribeTabBtn = document.getElementById('subscribeTabBtn');
    const cardTabContent = document.getElementById('cardTabContent');
    const subscribeTabContent = document.getElementById('subscribeTabContent');

    if (tab === 'card') {
        cardTabBtn.classList.add('border-blue-500', 'text-blue-600');
        cardTabBtn.classList.remove('border-transparent');
        subscribeTabBtn.classList.remove('border-blue-500', 'text-blue-600');
        subscribeTabBtn.classList.add('border-transparent');
        cardTabContent.classList.remove('hidden');
        subscribeTabContent.classList.add('hidden');
        // 重置卡密表单
        resetCardForm();
    } else {
        subscribeTabBtn.classList.add('border-blue-500', 'text-blue-600');
        subscribeTabBtn.classList.remove('border-transparent');
        cardTabBtn.classList.remove('border-blue-500', 'text-blue-600');
        cardTabBtn.classList.add('border-transparent');
        subscribeTabContent.classList.remove('hidden');
        cardTabContent.classList.add('hidden');
        // 加载当前授权信息
        loadCurrentAuth();
    }
}

// 重置卡密表单
function resetCardForm() {
    document.getElementById('cardCodeInput').value = '';
    document.getElementById('cardStep1').classList.remove('hidden');
    document.getElementById('cardStep2').classList.add('hidden');
    currentCardData = null;
    selectedChannelIds = [];
}

// 验证卡密
async function verifyCard() {
    const code = document.getElementById('cardCodeInput').value.trim();

    if (!code) {
        showToast('请输入卡密代码', 'error');
        return;
    }

    try {
        showLoading();
        const response = await authenticatedFetch(`${getApiBase()}/api/user/verify-card`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ code })
        });

        const result = await response.json();

        if (result.success) {
            // 构造卡密数据对象，适配后端返回的结构
            currentCardData = {
                code: code,
                template_name: result.template.name,
                template_id: result.template.id,
                validity_days: result.template.validity_days,
                max_channels: result.template.max_channels,
                channel_pool: result.available_channels.map(ch => String(ch.id)),
                available_channels: result.available_channels, // 保存完整的频道数据
                subscribed_channels: [] // TODO: 从用户订阅中获取已订阅的频道
            };
            showToast('卡密验证成功', 'success');
            showCardStep2();
        } else {
            showToast(result.error || '卡密验证失败', 'error');
        }
    } catch (error) {
        console.error('验证卡密失败:', error);
        showToast('网络错误', 'error');
    } finally {
        hideLoading();
    }
}

// 显示卡密步骤2: 选择频道
async function showCardStep2() {
    if (!currentCardData) return;

    // 更新卡密信息
    document.getElementById('cardTemplateName').textContent = currentCardData.template_name;
    document.getElementById('cardValidityDays').textContent = currentCardData.validity_days;
    document.getElementById('cardMaxChannels').textContent = currentCardData.max_channels;
    document.getElementById('maxCount').textContent = currentCardData.max_channels;

    // 加载频道池中的频道
    await loadCardChannels();

    // 切换到步骤2
    document.getElementById('cardStep1').classList.add('hidden');
    document.getElementById('cardStep2').classList.remove('hidden');
}

// 加载卡密可用频道
async function loadCardChannels() {
    const availableChannels = currentCardData.available_channels || [];

    try {
        const selector = document.getElementById('cardChannelSelector');

        if (availableChannels.length === 0) {
            selector.innerHTML = '<div class="text-center text-gray-500 py-4">暂无可选频道</div>';
            return;
        }

        selector.innerHTML = availableChannels.map(channel => {
            const isSubscribed = currentCardData.subscribed_channels.includes(channel.id);
            return `
                    <label class="flex items-center justify-between p-3 bg-gray-50 dark:bg-gray-800 rounded-lg cursor-pointer hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors ${isSubscribed ? 'opacity-50' : ''}">
                        <div class="flex items-center gap-3">
                            <input type="checkbox"
                                   class="channel-checkbox w-4 h-4 text-blue-600 rounded focus:ring-2 focus:ring-blue-500"
                                   value="${channel.id}"
                                   ${isSubscribed ? 'disabled checked' : ''}
                                   onchange="updateSelectedCount()">
                            <div class="flex-1">
                                <p class="font-medium">${channel.name}</p>
                            </div>
                        </div>
                        ${isSubscribed ? '<span class="text-xs text-green-600">已订阅</span>' : ''}
                    </label>
                `;
            }).join('');

        updateSelectedCount();
    } catch (error) {
        console.error('加载频道失败:', error);
        document.getElementById('cardChannelSelector').innerHTML = '<div class="text-center text-red-500 py-4">加载失败</div>';
    }
}

// 更新选中数量
function updateSelectedCount() {
    const checkboxes = document.querySelectorAll('.channel-checkbox:not(:disabled)');
    const checked = Array.from(checkboxes).filter(cb => cb.checked);
    selectedChannelIds = checked.map(cb => parseInt(cb.value));

    document.getElementById('selectedCount').textContent = selectedChannelIds.length;

    // 如果超过最大数量，禁用未选中的复选框
    const maxChannels = currentCardData.max_channels;
    checkboxes.forEach(cb => {
        if (!cb.checked && selectedChannelIds.length >= maxChannels) {
            cb.disabled = true;
        } else if (!cb.checked) {
            cb.disabled = false;
        }
    });
}

// 返回卡密步骤1
function backToCardStep1() {
    document.getElementById('cardStep1').classList.remove('hidden');
    document.getElementById('cardStep2').classList.add('hidden');
    document.getElementById('cardCodeInput').value = '';
}

// 激活卡密
async function activateCard() {
    if (!currentCardData) {
        showToast('请先验证卡密', 'error');
        return;
    }

    if (selectedChannelIds.length === 0) {
        showToast('请至少选择一个频道', 'error');
        return;
    }

    try {
        showLoading();
        const response = await authenticatedFetch(`${getApiBase()}/api/user/activate-card`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                code: currentCardData.code,
                selected_channels: selectedChannelIds
            })
        });

        const result = await response.json();

        if (result.success) {
            showToast('卡密激活成功！', 'success');
            closeAuthModal();
            // 刷新频道列表
            setTimeout(() => {
                loadChannels();
                loadCurrentAuth();
            }, 500);
        } else {
            showToast(result.message || '卡密激活失败', 'error');
        }
    } catch (error) {
        console.error('激活卡密失败:', error);
        showToast('网络错误', 'error');
    } finally {
        hideLoading();
    }
}

// 加载当前授权信息
async function loadCurrentAuth() {
    const token = localStorage.getItem('token');
    if (!token) return;

    try {
        const response = await authenticatedFetch(`${getApiBase()}/api/user/subscriptions`, {
            headers: {}
        });

        const result = await response.json();

        if (result.success) {
            const subscriptions = result.subscriptions || [];

            // 计算到期时间
            const expiries = subscriptions.map(sub => new Date(sub.expires_at));
            const maxExpiry = expiries.length > 0 ? new Date(Math.max(...expiries)) : null;

            if (maxExpiry) {
                const now = new Date();
                const diffTime = Math.abs(maxExpiry - now);
                const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));

                document.getElementById('currentExpiry').textContent = maxExpiry.toLocaleDateString('zh-CN');
                document.getElementById('remainingDays').textContent = `${diffDays} 天`;
            } else {
                document.getElementById('currentExpiry').textContent = '无授权';
                document.getElementById('remainingDays').textContent = '-';
            }

            // 加载订阅频道列表
            loadSubscribedChannels(subscriptions);
        }
    } catch (error) {
        console.error('加载授权信息失败:', error);
    }
}

// 加载已订阅频道列表
async function loadSubscribedChannels(subscriptions) {
    try {
        const response = await authenticatedFetch(`${getApiBase()}/api/channels?admin=true`, {
            headers: {}
        });

        const result = await response.json();

        if (result.success && result.channels) {
            // 只显示私人频道
            const channels = result.channels.filter(ch => ch.type === 'private');
            const container = document.getElementById('subscribeChannelList');

            if (channels.length === 0) {
                container.innerHTML = '<div class="text-center text-gray-500 py-4">暂无频道</div>';
                return;
            }

            container.innerHTML = channels.map(channel => {
                const subscription = subscriptions.find(sub => sub.channel_id === channel.id);
                const isSubscribed = !!subscription;

                return `
                    <div class="flex items-center justify-between p-3 bg-gray-50 dark:bg-gray-800 rounded-lg">
                        <div class="flex-1">
                            <p class="font-medium">${channel.name}</p>
                            <p class="text-xs text-gray-500">
                                ${isSubscribed ? `到期: ${new Date(subscription.expires_at).toLocaleDateString('zh-CN')}` : '未订阅'}
                            </p>
                        </div>
                        <button onclick="toggleSubscription(${channel.id})" class="px-3 py-1 text-sm rounded-lg transition-colors ${
                            isSubscribed
                                ? 'bg-gray-200 dark:bg-gray-700 hover:bg-gray-300 dark:hover:bg-gray-600'
                                : 'bg-gradient-to-r from-blue-500 to-indigo-600 hover:from-blue-600 hover:to-indigo-700 text-white'
                        }">
                            ${isSubscribed ? '退订' : '订阅'}
                        </button>
                    </div>
                `;
            }).join('');
        }
    } catch (error) {
        console.error('加载频道列表失败:', error);
    }
}

// 切换订阅状态（这个功能需要后端API支持，暂时保留）
function toggleSubscription(channelId) {
    showToast('此功能暂未开放，请使用卡密订阅', 'info');
}

function showSettingsModal() {
    const modal = document.getElementById('settingsModal');
    modal.classList.remove('hidden');
    modal.classList.add('flex');
}

function closeSettingsModal() {
    const modal = document.getElementById('settingsModal');
    modal.classList.add('hidden');
    modal.classList.remove('flex');
}

// 功能按钮
function showMessages() {
    // 切换到主视图
    const mainView = document.getElementById('mainView');
    const dashboardView = document.getElementById('dashboardView');

    if (mainView && dashboardView) {
        mainView.classList.remove('hidden');
        dashboardView.classList.add('hidden');
    }
}

function showDashboard() {
    // 切换到盘面视图
    const mainView = document.getElementById('mainView');
    const dashboardView = document.getElementById('dashboardView');

    if (mainView && dashboardView) {
        mainView.classList.add('hidden');
        dashboardView.classList.remove('hidden');
    }
}

function showSettings() {
    // 检查登录状态
    const token = localStorage.getItem('token');
    if (!token) {
        // 未登录，直接跳转登录页
        window.location.href = 'auth.html';
        return;
    }
    showSettingsModal();
}

// 认证功能
function handleAuth() {
    const token = localStorage.getItem('token');

    if (token) {
        // 已登录，执行退出（不再确认）
        logout();
    } else {
        // 未登录，跳转到登录页
        window.location.href = 'auth.html';
    }
}

// 退出登录
async function logout() {
    const token = localStorage.getItem('token');
    if (!token) {
        window.location.href = 'auth.html';
        return;
    }

    try {
        // 调用后端退出接口
        await fetch(`${API_BASE}/api/auth/logout`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            }
        });
    } catch (error) {
        console.error('登出失败:', error);
    } finally {
        // 清除本地存储
        localStorage.removeItem('token');
        localStorage.removeItem('user');

        // 显示退出成功提示
        showToast('已退出登录', 'success');

        // 延迟刷新页面，让用户看到提示
        setTimeout(() => {
            window.location.reload();
        }, 500);
    }
}

// Toast 提示
function showToast(message, type = 'success') {
    let container = document.getElementById('toastContainer');
    if (!container) {
        // 如果容器不存在，创建一个
        container = document.createElement('div');
        container.id = 'toastContainer';
        container.className = 'fixed top-4 right-4 z-50 space-y-2';
        document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    const bgColor = type === 'success' ? 'bg-green-500' : 'bg-red-500';
    const icon = type === 'success' ? 'fa-check-circle' : 'fa-exclamation-circle';

    toast.className = `${bgColor} text-white px-6 py-3 rounded-lg shadow-lg flex items-center gap-3 toast-enter`;
    toast.innerHTML = `
        <i class="fas ${icon}"></i>
        <span class="font-medium">${message}</span>
    `;

    container.appendChild(toast);

    setTimeout(() => {
        toast.classList.remove('toast-enter');
        toast.classList.add('toast-exit');
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// 更新认证按钮显示
function updateAuthButton() {
    const token = localStorage.getItem('token');
    const loginBtn = document.getElementById('loginBtn');
    const userActions = document.getElementById('userActions');
    const userNickname = document.getElementById('userNickname');

    if (token) {
        // 已登录，显示昵称 + 退出按钮
        const user = getUser();
        if (user) {
            loginBtn.classList.add('hidden');
            userActions.classList.remove('hidden');
            userNickname.textContent = user.nickname;
        }
    } else {
        // 未登录，显示登录按钮
        loginBtn.classList.remove('hidden');
        userActions.classList.add('hidden');
    }
}

// 加载豆包AI总结
async function loadDoubaiSummary(channelId, isLoadMore = false) {
    const summaryContainer = document.getElementById('dailySummary');
    if (!summaryContainer) return;

    // 初始加载时重置分页
    if (!isLoadMore) {
        doubaoOffset[channelId] = 0;
        doubaoTotal[channelId] = 0;
    }

    try {
        const offset = doubaoOffset[channelId] || 0;
        const total = doubaoTotal[channelId] || 0;

        // 检查是否还有更多
        if (isLoadMore && offset >= total) {
            // 移除加载图标
            const loadingEl = document.getElementById('doubao-loading-more');
            if (loadingEl) loadingEl.remove();
            isLoadingMoreDoubao = false;
            return;
        }

        const response = await fetch(`${getApiBase()}/api/channel/doubao-summary?channel_id=${channelId}&offset=${offset}&limit=10`);
        const data = await response.json();

        if (data.success && data.summary) {
            const messages = data.summary.messages;
            const hasMore = data.summary.has_more;

            // 更新分页信息
            doubaoOffset[channelId] = data.summary.offset;
            doubaoTotal[channelId] = data.summary.total;

            if (!messages || messages.length === 0) {
                if (!isLoadMore) {
                    summaryContainer.innerHTML = `
                        <div class="h-full flex flex-col items-center justify-center text-gray-400 text-sm">
                            <i class="fas fa-info-circle mb-2 text-4xl opacity-50"></i>
                            <p>暂无AI分析结果</p>
                        </div>
                    `;
                }
            } else {
                let html = '<div class="space-y-3">';

                // 反转数组，让最新的在下面（历史在上，最新在下）
                [...messages].reverse().forEach((msg, index) => {
                    // 格式化时间
                    const time = new Date(msg.timestamp).toLocaleString('zh-CN', {
                        month: '2-digit',
                        day: '2-digit',
                        hour: '2-digit',
                        minute: '2-digit'
                    });

                    // 操作颜色映射
                    const operateColors = {
                        '买入': 'text-red-500',
                        '看好': 'text-red-400',
                        '加仓': 'text-red-600',
                        '卖出': 'text-green-500',
                        '看空': 'text-green-400',
                        '减仓': 'text-green-600',
                        '持有': 'text-blue-500',
                        '观望': 'text-gray-600'
                    };

                    const operateBgColors = {
                        '买入': 'bg-red-50',
                        '看好': 'bg-red-50',
                        '加仓': 'bg-red-50',
                        '卖出': 'bg-green-50',
                        '看空': 'bg-green-50',
                        '减仓': 'bg-green-50',
                        '持有': 'bg-blue-50',
                        '观望': 'bg-gray-100'
                    };

                    html += `
                        <div class="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm hover:shadow-md transition-shadow overflow-hidden cursor-pointer hover:border-blue-300 dark:hover:border-blue-600"
                             onclick="showOriginalMessage(${msg.id})">
                            <!-- 时间戳标题栏 -->
                            <div class="px-3 py-2 bg-gray-50 dark:bg-gray-900/50 border-b border-gray-200 dark:border-gray-700">
                                <span class="text-xs font-semibold text-gray-600 dark:text-gray-400">${time}</span>
                            </div>
                            <!-- 股票列表 -->
                            <div class="p-3 space-y-2">
                    `;

                    msg.stocks.forEach(stock => {
                        const colorClass = operateColors[stock.operate] || 'text-gray-600';
                        const bgColorClass = operateBgColors[stock.operate] || 'bg-gray-50';

                        html += `
                            <div class="flex items-center justify-between p-2 rounded-lg ${bgColorClass} dark:bg-opacity-20 border border-gray-100 dark:border-gray-700 hover:border-opacity-50 transition-colors">
                                <div class="flex items-center gap-2 flex-1">
                                    <div>
                                        <span class="font-semibold text-sm text-gray-900 dark:text-gray-100">${stock.stock_name}</span>
                                        ${stock.stock_code ? `<span class="text-xs text-gray-500 dark:text-gray-400 ml-1">${stock.stock_code}</span>` : ''}
                                    </div>
                                </div>
                                <span class="px-3 py-1 rounded-md text-sm font-bold ${colorClass}">${stock.operate}</span>
                            </div>
                        `;
                    });

                    html += `
                            </div>
                        </div>
                    `;
                });

                html += '</div>';

                if (isLoadMore) {
                    // 增量加载：插入到顶部（历史消息在上方）
                    const loadMoreEl = document.getElementById('doubao-load-more');
                    if (loadMoreEl) loadMoreEl.remove();

                    // 移除加载图标
                    const loadingEl = document.getElementById('doubao-loading-more');
                    if (loadingEl) loadingEl.remove();

                    // 创建临时容器
                    const tempDiv = document.createElement('div');
                    tempDiv.innerHTML = html;

                    // 获取消息容器（第一个div.space-y-3）
                    let messagesContainer = summaryContainer.querySelector('.space-y-3');
                    if (!messagesContainer) {
                        messagesContainer = summaryContainer.firstElementChild;
                    }

                    // 插入到现有消息前面
                    if (messagesContainer) {
                        messagesContainer.insertAdjacentHTML('beforebegin', tempDiv.innerHTML);
                    } else {
                        summaryContainer.insertAdjacentHTML('afterbegin', tempDiv.innerHTML);
                    }
                } else {
                    // 初始加载：替换全部
                    summaryContainer.innerHTML = html;

                    // 初始加载后滚动到底部（显示最新的）
                    setTimeout(() => {
                        summaryContainer.scrollTop = summaryContainer.scrollHeight;
                    }, 100);

                    // 设置滚动监听
                    setupDoubaoScrollListener(channelId);
                }
            }
        } else {
            if (!isLoadMore) {
                summaryContainer.innerHTML = `
                    <div class="h-full flex flex-col items-center justify-center text-gray-400 text-sm">
                        <i class="fas fa-info-circle mb-2 text-4xl opacity-50"></i>
                        <p>加载失败</p>
                    </div>
                `;
            }
        }
    } catch (error) {
        console.error('加载豆包AI总结失败:', error);
        if (!isLoadMore) {
            summaryContainer.innerHTML = `
                <div class="h-full flex flex-col items-center justify-center text-gray-400 text-sm">
                    <i class="fas fa-info-circle mb-2 text-4xl opacity-50"></i>
                    <p>加载失败</p>
                </div>
            `;
        }
    } finally {
        isLoadingMoreDoubao = false;
    }
}

// 加载更多豆包分析
async function loadMoreDoubaoSummary(channelId) {
    if (isLoadingMoreDoubao) return;
    isLoadingMoreDoubao = true;

    const summaryContainer = document.getElementById('dailySummary');

    // 移除旧的加载图标
    const oldLoading = document.getElementById('doubao-loading-more');
    if (oldLoading) oldLoading.remove();

    // 创建新的加载图标并插入到顶部
    const loadMoreDiv = document.createElement('div');
    loadMoreDiv.id = 'doubao-loading-more';
    loadMoreDiv.className = 'text-center py-3';
    loadMoreDiv.innerHTML = '<i class="fas fa-spinner fa-spin text-blue-500"></i>';

    // 插入到最顶部，因为是在加载历史消息（会在顶部显示）
    summaryContainer.insertAdjacentElement('afterbegin', loadMoreDiv);

    await loadDoubaiSummary(channelId, true);
}

// 设置豆包总结滚动监听
function setupDoubaoScrollListener(channelId) {
    const summaryContainer = document.getElementById('dailySummary');
    if (!summaryContainer) return;

    // 移除旧的监听器（通过标记）
    summaryContainer.removeEventListener('scroll', summaryContainer._doubaoScrollHandler);

    // 创建防抖的滚动处理
    let scrollTimeout = null;
    const scrollHandler = () => {
        if (scrollTimeout) clearTimeout(scrollTimeout);

        scrollTimeout = setTimeout(() => {
            // 当滚动到顶部20%时加载更多历史消息
            const scrollRatio = summaryContainer.scrollTop / (summaryContainer.scrollHeight - summaryContainer.clientHeight);
            if (scrollRatio < 0.2) {
                loadMoreDoubaoSummary(channelId);
            }
        }, 100); // 100ms防抖
    };

    // 保存handler引用以便移除
    summaryContainer._doubaoScrollHandler = scrollHandler;
    summaryContainer.addEventListener('scroll', scrollHandler);
}

// 显示原文消息
async function showOriginalMessage(messageId) {
    try {
        const response = await fetch(`${getApiBase()}/api/messages/${messageId}`);
        const data = await response.json();

        if (data.success && data.message) {
            const msg = data.message;

            // 解析AI分析结果
            let aiSummaryHTML = '';
            if (msg.doubao_ai) {
                try {
                    const doubaoData = JSON.parse(msg.doubao_ai);
                    const stockList = doubaoData.stock_list || [];

                    if (stockList.length > 0) {
                        // 操作颜色映射
                        const operateColors = {
                            '买入': 'text-red-500',
                            '看好': 'text-red-400',
                            '加仓': 'text-red-600',
                            '卖出': 'text-green-500',
                            '看空': 'text-green-400',
                            '减仓': 'text-green-600',
                            '持有': 'text-blue-500',
                            '观望': 'text-gray-600'
                        };

                        const operateBgColors = {
                            '买入': 'bg-red-50',
                            '看好': 'bg-red-50',
                            '加仓': 'bg-red-50',
                            '卖出': 'bg-green-50',
                            '看空': 'bg-green-50',
                            '减仓': 'bg-green-50',
                            '持有': 'bg-blue-50',
                            '观望': 'bg-gray-100'
                        };

                        aiSummaryHTML = `
                            <div class="mt-4 pt-4 border-t border-gray-200 dark:border-gray-700">
                                <h5 class="text-sm font-semibold text-gray-900 dark:text-white mb-3 flex items-center gap-2">
                                    <i class="fas fa-robot text-blue-500"></i>
                                    AI观点
                                </h5>
                                <div class="space-y-2">
                        `;

                        stockList.forEach(stock => {
                            const colorClass = operateColors[stock.operate] || 'text-gray-600';
                            const bgColorClass = operateBgColors[stock.operate] || 'bg-gray-50';

                            aiSummaryHTML += `
                                <div class="flex items-center justify-between p-2 rounded-lg ${bgColorClass} dark:bg-opacity-20 border border-gray-100 dark:border-gray-700">
                                    <div class="flex items-center gap-2 flex-1">
                                        <span class="font-semibold text-sm text-gray-900 dark:text-gray-100">${stock.stock_name}</span>
                                        ${stock.stock_code ? `<span class="text-xs text-gray-500 dark:text-gray-400">${stock.stock_code}</span>` : ''}
                                    </div>
                                    <span class="px-3 py-1 rounded-md text-sm font-bold ${colorClass}">${stock.operate}</span>
                                </div>
                            `;
                        });

                        aiSummaryHTML += `
                                </div>
                            </div>
                        `;
                    }
                } catch (e) {
                    console.error('解析AI分析失败:', e);
                }
            }

            // 创建模态框显示原文
            const modal = document.createElement('div');
            modal.className = 'fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4';
            modal.onclick = (e) => {
                if (e.target === modal) modal.remove();
            };

            const content = msg.content
                .replace(/!\[([^\]]*)\]\(([^)]+)\)/g, '<img src="$2" alt="$1" class="max-w-full h-auto rounded my-2" />')
                .replace(/\n/g, '<br>');

            modal.innerHTML = `
                <div class="bg-white dark:bg-gray-800 rounded-xl shadow-2xl max-w-2xl w-full max-h-[80vh] overflow-hidden flex flex-col">
                    <div class="px-4 py-3 border-b border-gray-200 dark:border-gray-700 flex justify-between items-center">
                        <h3 class="text-lg font-semibold text-gray-900 dark:text-white">原文消息</h3>
                        <button onclick="this.closest('.fixed').remove()" class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">
                            <i class="fas fa-times text-xl"></i>
                        </button>
                    </div>
                    <div class="p-4 overflow-y-auto flex-1">
                        ${msg.title ? `<h4 class="font-semibold text-gray-900 dark:text-white mb-2">${msg.title}</h4>` : ''}
                        <div class="text-gray-700 dark:text-gray-300 text-sm leading-relaxed">
                            ${content}
                        </div>
                        ${aiSummaryHTML}
                        <p class="text-xs text-gray-400 mt-4">${new Date(msg.created_at).toLocaleString('zh-CN')}</p>
                    </div>
                </div>
            `;

            document.body.appendChild(modal);
        } else {
            showToast('消息不存在', 'error');
        }
    } catch (error) {
        console.error('获取原文失败:', error);
        showToast('加载失败', 'error');
    }
}

function redeemCode() {
    const code = document.getElementById('redeemCode').value;
    if (!code) {
        alert('请输入兑换码');
        return;
    }

    // TODO: 调用后端API验证兑换码
    alert(`兑换码 "${code}" 验证中...`);
}

// 说明书模态框控制
function showDocsModal() {
    const modal = document.getElementById('docsModal');
    if (!modal) {
        console.error('docsModal element not found');
        return;
    }
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    document.body.style.overflow = 'hidden';
}

function closeDocsModal() {
    const modal = document.getElementById('docsModal');
    modal.classList.add('hidden');
    modal.classList.remove('flex');
    document.body.style.overflow = '';
}

// ESC键关闭说明书
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
        closeDocsModal();
    }
});

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', () => {
    init();

    // 初始化图片查看器
    setupImageViewer();
});

// Tab 切换使用 onclick 直接绑定（在 index_user.html 中）
