// 全局变量
let socket = null;
let currentChannel = null;
let currentTab = 'public'; // 'private' or 'public'
let currentCategory = 'all'; // 当前选中的分类
let isDarkMode = false;
let isLoggedIn = false;

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

// 加载频道列表
async function loadChannels() {
    try {
        const host = window.location.hostname;
        let url = `http://${host}:5555/api/channels`;

        // 如果用户已登录，传递用户ID作为socket_id获取用户有权限的频道
        const user = getUser();
        if (user && user.id) {
            url += `?socket_id=${user.id}`;
        }

        const response = await fetch(url);
        const data = await response.json();

        if (data.channels) {
            allChannels = data.channels;
        }
    } catch (error) {
        console.error('加载频道列表失败:', error);
    }
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
        const response = await fetch(`http://${host}:5555/api/categories?type=${categoryType}`);
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
                fetch(`http://${window.location.hostname}:5555/api/categories?type=public`)
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
                fetch(`http://${window.location.hostname}:5555/api/categories?type=private`)
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

// 加载所有频道的最新消息摘要
async function loadAllChannelsLatestMessages() {
    if (allChannels.length === 0) return;

    const host = window.location.hostname;
    const user = getUser();
    const user_id = user ? user.id : null;

    if (!user_id) {
        console.log('未登录用户，跳过加载私人频道信息');
        return;
    }

    try {
        // 使用新的批量API，一次请求获取所有频道信息
        const response = await fetch(`http://${host}:5555/api/ws/channels-summary`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                socket_id: user_id
            })
        });

        const data = await response.json();
        if (data.success && data.channels) {
            // 保存所有频道的未读数
            if (data.unread_counts) {
                Object.keys(data.unread_counts).forEach(chId => {
                    unreadCounts[chId] = data.unread_counts[chId];
                });
            }

            // 保存每个频道的最新消息
            data.channels.forEach(channel => {
                if (channel.latest_message) {
                    // 提取纯文本内容
                    let msgText = channel.latest_message.content || '';
                    // Markdown图片格式替换为 [图片] 文本
                    msgText = msgText.replace(/!\[([^\]]*)\]\([^)]+\)/g, '[图片]');
                    // 截断长度
                    if (msgText.length > 30) {
                        msgText = msgText.substring(0, 30) + '...';
                    }
                    channelLatestMessage[channel.id] = msgText;
                    channelLatestTime[channel.id] = channel.latest_message.timestamp;
                }
            });
        }
    } catch (error) {
        console.error('批量加载频道信息失败:', error);
    }
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
    const wsUrl = window.getWebSocketUrl ? window.getWebSocketUrl() : `ws://${window.location.hostname}:9080`;

    socket = io(wsUrl, {
        transports: ['websocket', 'polling']
    });

    socket.on('connect', async () => {
        updateWSStatus(true);
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

        const response = await fetch(`http://${window.location.hostname}:5555/api/ws/subscribe`, {
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

        // 按最新消息时间排序（有最新消息的排前面）
        channels.sort((a, b) => {
            const timeA = channelLatestTime[a.id] || 0;
            const timeB = channelLatestTime[b.id] || 0;
            return timeB - timeA; // 降序，最新的在前
        });

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
                ${latestMsg ? `<p class="text-xs text-gray-500 truncate">${latestMsg}</p>` : ''}
            </div>
        </div>
    `;
}

// 切换标签页
function switchTab(tab) {
    // 切换到私人订阅时检查登录
    if (tab === 'private') {
        const token = localStorage.getItem('token');
        if (!token) {
            // 未登录，直接跳转登录页
            window.location.href = 'login.html';
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

    // 重新渲染频道列表
    currentChannel = null;
    renderChannelList();
    clearMessages();
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
        window.location.href = 'login.html';
        return;
    }

    currentChannel = channelId;

    // 立即清除本地未读数（快速响应）
    if (unreadCounts[channelId]) {
        unreadCounts[channelId] = 0;
        renderChannelList(); // 立即更新UI
    }

    // 通知后端清除未读数
    try {
        const host = window.location.hostname;
        const user = getUser();
        if (user && user.id) {
            await fetch(`http://${host}:5555/api/ws/mark-read`, {
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

        const response = await fetch(`http://${host}:5555/api/ws/switch-channel`, {
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
    content = content.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, '<img src="$2" alt="$1" class="max-w-full h-auto rounded" loading="lazy" />');

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
            <div class="message-box bg-white dark:bg-dark-surface rounded-lg p-4 shadow-sm border border-gray-200 dark:border-gray-700">
                ${titleHTML}
                <div class="message-content text-gray-700 dark:text-gray-300">${content}</div>
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

// 处理新消息
function handleNewMessage(message) {
    // 更新最新消息缓存
    if (message.channel_id && message.content) {
        let msgText = message.content;
        msgText = msgText.replace(/<[^>]*>/g, '');
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
}

function closeAuthModal() {
    const modal = document.getElementById('authModal');
    modal.classList.add('hidden');
    modal.classList.remove('flex');
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
    // 已在主界面
}

function showDashboard() {
    alert('盘面分析功能开发中...');
}

function showSettings() {
    // 检查登录状态
    const token = localStorage.getItem('token');
    if (!token) {
        // 未登录，直接跳转登录页
        window.location.href = 'login.html';
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
        window.location.href = 'login.html';
    }
}

// 退出登录
async function logout() {
    const token = localStorage.getItem('token');
    if (!token) {
        window.location.href = 'login.html';
        return;
    }

    try {
        // 调用后端退出接口
        await fetch(`${window.location.protocol}//${window.location.hostname}:5555/api/auth/logout`, {
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
    const container = document.getElementById('toastContainer');
    if (!container) {
        // 如果容器不存在，创建一个
        const toastContainer = document.createElement('div');
        toastContainer.id = 'toastContainer';
        toastContainer.className = 'fixed top-4 right-4 z-50 space-y-2';
        document.body.appendChild(toastContainer);
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

function redeemCode() {
    const code = document.getElementById('redeemCode').value;
    if (!code) {
        alert('请输入兑换码');
        return;
    }

    // TODO: 调用后端API验证兑换码
    alert(`兑换码 "${code}" 验证中...`);
}

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', () => {
    init();

    // 初始化图片查看器
    setupImageViewer();
});

// Tab 切换使用 onclick 直接绑定（在 index_user.html 中）
