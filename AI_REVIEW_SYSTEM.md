# AI消息核对系统 - 完整开发方案

## 项目概述

在管理端的消息管理Tab下方新增"AI消息核对"功能，通过键盘交互快速核对和修正AI分析的股票信息，支持股票名称/代码联想搜索，每日凌晨3点自动同步股票数据。

---

## 核心需求

### 功能需求
1. **筛选条件**：支持多选频道、选择日期范围
2. **核对模式**：键盘交互（↑↓←→Enter）快速判断AI分析正确性
3. **直接修正**：错误时直接修改 `messages.doubao_ai` 字段
4. **股票联想**：支持拼音、首字母、代码、名称模糊搜索
5. **自动同步**：每日凌晨3点从Baostock同步股票数据
6. **进度保存**：记录核对进度，支持断点续传

### 交互需求
- **↑ 上键**：查看上一条消息
- **↓ 下键**：查看下一条消息
- **← 左键**：标记为"正确"，跳到下一条
- **→ 右键**：标记为"错误"，进入修正模式
- **Enter键**：跳过当前消息
- **Esc键**：退出输入模式

### 数据需求
- 股票数据：代码、名称、拼音、首字母、市场
- 同步日志：记录每次同步的结果和耗时
- 直接修改：不保留历史记录，直接更新源数据

---

## 数据库设计

### 1. 股票基础表 (stocks)

```sql
CREATE TABLE IF NOT EXISTS stocks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code VARCHAR(10) NOT NULL UNIQUE,        -- 股票代码：600000
    name VARCHAR(50) NOT NULL,               -- 股票名称：三一重工
    pinyin VARCHAR(100),                      -- 全拼：sanyizhonggong
    pinyin_abbr VARCHAR(20),                  -- 首字母：syzg
    market VARCHAR(10),                       -- 市场：sh/sz
    status INTEGER DEFAULT 1,                 -- 状态：1上市 0退市
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 索引
CREATE INDEX idx_stocks_code ON stocks(code);
CREATE INDEX idx_stocks_pinyin ON stocks(pinyin);
CREATE INDEX idx_stocks_abbr ON stocks(pinyin_abbr);
CREATE INDEX idx_stocks_status ON stocks(status);
```

### 2. 同步日志表 (stock_sync_logs)

```sql
CREATE TABLE IF NOT EXISTS stock_sync_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sync_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    total_count INTEGER,                      -- 同步总数
    new_count INTEGER,                        -- 新增数量
    update_count INTEGER,                     -- 更新数量
    error_count INTEGER,                      -- 错误数量
    status VARCHAR(20),                       -- success/failed
    error_message TEXT,
    duration_seconds INTEGER
);

CREATE INDEX idx_sync_time ON stock_sync_logs(sync_time);
```

### 3. 消息表已存在，无需新建

直接使用现有 `messages` 表，修改其 `doubao_ai` 字段即可。

---

## 技术栈

### 后端
- **Python**: 3.8+
- **Flask**: 现有框架
- **APScheduler**: 定时任务
- **Baostock**: 股票数据源
- **Pinyin**: 拼音转换

### 前端
- **Vue 3**: Composition API
- **Element Plus**: UI组件库
- **@vueuse/core**: 工具库
- **pinyin-pro**: 拼音匹配

---

## 开发阶段划分

### Phase 1: 股票数据同步 (优先级：P0)
**目标**：建立股票数据库，每日凌晨3点自动更新

#### 任务清单
- [ ] 创建数据库表 (`stocks`, `stock_sync_logs`)
- [ ] 实现 `fetch_stocks_from_baostock()` 函数
- [ ] 实现拼音转换逻辑
- [ ] 实现数据库保存逻辑（增量更新）
- [ ] 集成APScheduler定时任务
- [ ] 添加同步日志记录
- [ ] 测试同步功能

#### 文件清单
```
backend/
├── stock_sync.py              # 新建：股票同步模块
│   ├── fetch_stocks_from_baostock()
│   ├── convert_to_pinyin()
│   └── save_to_database()
├── database.py                 # 修改：添加股票相关查询
└── push_api.py                 # 修改：集成定时任务
```

#### 核心代码骨架

```python
# backend/stock_sync.py
import baostock as bs
import pandas as pd
from pypinyin import lazy_pinyin
from apscheduler.schedulers.background import BackgroundScheduler
import logging

logger = logging.getLogger(__name__)

def fetch_stocks_from_baostock():
    """从Baostock获取所有A股股票数据"""
    # TODO: 实现登录、查询、过滤逻辑
    pass

def convert_to_pinyin(name):
    """将股票名称转为拼音和首字母"""
    py = lazy_pinyin(name)
    return {
        'pinyin': ''.join(py),
        'abbr': ''.join([x[0] for x in py])
    }

def save_to_database(df):
    """保存到数据库，支持增量更新"""
    # TODO: 实现INSERT/UPDATE逻辑
    pass

def sync_stock_data():
    """定时任务入口函数"""
    logger.info("开始同步股票数据...")
    try:
        df = fetch_stocks_from_baostock()
        save_to_database(df)
        logger.info(f"同步完成，共 {len(df)} 只股票")
    except Exception as e:
        logger.error(f"同步失败: {e}")

# 启动定时任务
scheduler = BackgroundScheduler()
scheduler.add_job(
    sync_stock_data,
    trigger='cron',
    hour=3,
    minute=0,
    id='daily_stock_sync'
)
scheduler.start()
```

---

### Phase 2: 后端API开发 (优先级：P0)
**目标**：提供核对所需的所有API接口

#### 任务清单
- [ ] 获取待核对消息列表接口
- [ ] 获取单条消息详情接口
- [ ] 提交修正结果接口
- [ ] 股票搜索联想接口
- [ ] 手动触发同步接口
- [ ] 获取同步状态接口

#### 文件清单
```
backend/
└── push_api.py                 # 修改：添加API路由

# 新增路由
GET  /api/admin/review/pending              # 获取待核对列表
GET  /api/admin/review/message/<id>         # 获取消息详情
POST /api/admin/review/correct             # 提交修正
GET  /api/admin/stocks/search?q=xxx        # 股票搜索
POST /api/admin/stocks/sync                 # 手动同步
GET  /api/admin/stocks/sync-status          # 同步状态
GET  /api/admin/stocks/sync-logs            # 同步日志
```

#### API设计

```python
# 1. 获取待核对消息列表
@app.route('/api/admin/review/pending', methods=['GET'])
def get_pending_messages():
    """
    获取待核对消息列表
    参数:
        channel_ids: 频道ID列表（逗号分隔）
        start_date: 开始日期
        end_date: 结束日期
        page: 页码
        size: 每页数量
    """
    channel_ids = request.args.get('channel_ids', '').split(',')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    page = request.args.get('page', 1, type=int)
    size = request.args.get('size', 20, type=int)

    # 查询有AI分析的消息
    messages = get_messages_with_ai(
        channel_ids=channel_ids,
        start_date=start_date,
        end_date=end_date,
        page=page,
        size=size
    )

    return jsonify({'success': True, 'messages': messages})

# 2. 提交修正结果
@app.route('/api/admin/review/correct', methods=['POST'])
def correct_ai_result():
    """
    直接修正AI分析结果
    Body:
        {
            "message_id": 123,
            "stocks": [
                {"stock_name": "三一重工", "stock_code": "600031", "operate": "买入"}
            ],
            "reviewed_by": "admin"
        }
    """
    data = request.json
    message_id = data.get('message_id')
    stocks = data.get('stocks', [])
    reviewed_by = data.get('reviewed_by', 'admin')

    # 更新messages表的doubao_ai字段
    doubao_result = json.dumps({"stock_list": stocks}, ensure_ascii=False)
    update_message_doubao(message_id, doubao_result)

    logger.info(f"消息 {message_id} AI结果已修正 by {reviewed_by}")

    return jsonify({'success': True})

# 3. 股票搜索联想
@app.route('/api/admin/stocks/search', methods=['GET'])
def search_stocks():
    """
    股票联想搜索
    参数:
        q: 搜索关键词（代码/名称/拼音/首字母）
    """
    query = request.args.get('q', '')

    stocks = search_stocks_from_db(query)

    return jsonify({'success': True, 'stocks': stocks})
```

---

### Phase 3: 前端界面开发 (优先级：P1)
**目标**：实现核对界面布局

#### 任务清单
- [ ] 创建核对页面组件
- [ ] 实现筛选条件栏
- [ ] 实现三栏布局（消息列表/消息详情/核对面板）
- [ ] 实现股票输入组件
- [ ] 实现进度显示

#### 文件清单
```
frontend/admin/
└── review.html                  # 新建：核对页面

frontend/admin/js/
└── review.js                    # 新建：核对逻辑
```

#### 界面布局

```html
<!-- 顶部筛选栏 -->
<div class="filter-bar">
  <el-select v-model="selectedChannels" multiple placeholder="选择频道">
    <!-- 频道选项 -->
  </el-select>

  <el-date-picker v-model="dateRange" type="daterange">
  </el-date-picker>

  <el-button type="primary" @click="startReview">开始核对</el-button>

  <span class="progress">进度: {{ currentIndex }} / {{ total }}</span>
</div>

<!-- 三栏工作区 -->
<div class="workspace">
  <!-- 左侧：消息列表 -->
  <div class="message-list">
    <div v-for="msg in messages"
         :key="msg.id"
         :class="{active: currentMessageId === msg.id}"
         @click="selectMessage(msg.id)">
      <div class="status">{{ msg.status }}</div>
      <div class="preview">{{ msg.content }}</div>
    </div>
  </div>

  <!-- 中间：消息详情 -->
  <div class="message-detail">
    <div class="ai-result">
      <h4>AI分析结果</h4>
      <div v-for="stock in currentMessage.stocks" :key="stock.stock_name">
        {{ stock.stock_name }} ({{ stock.stock_code }}): {{ stock.operate }}
      </div>
    </div>

    <div class="original-message">
      <h4>原始消息</h4>
      <p>{{ currentMessage.content }}</p>
    </div>

    <div class="keyboard-hints">
      <span>↑↓ 切换消息</span>
      <span>← 正确</span>
      <span>→ 错误</span>
      <span>Enter 跳过</span>
    </div>
  </div>

  <!-- 右侧：核对面板 -->
  <div class="review-panel">
    <div class="result-display">
      <h4>核对结果</h4>
      <el-tag v-if="reviewStatus === 'correct'" type="success">✓ 正确</el-tag>
      <el-tag v-if="reviewStatus === 'wrong'" type="danger">✗ 错误</el-tag>
      <el-tag v-if="reviewStatus === 'skipped'" type="info">⊘ 跳过</el-tag>
    </div>

    <div v-if="reviewStatus === 'wrong'" class="stock-input">
      <h4>输入正确股票</h4>
      <el-input
        v-model="stockSearch"
        placeholder="输入代码/名称/拼音"
        @input="onStockSearch"
      >
        <template #append>
          <el-button icon="Plus" @click="addStock">添加</el-button>
        </template>
      </el-input>

      <div class="stock-suggestions">
        <div v-for="stock in suggestions" :key="stock.code"
             @click="selectStock(stock)">
          {{ stock.name }} ({{ stock.code }})
        </div>
      </div>

      <div class="added-stocks">
        <el-tag v-for="stock in correctedStocks" :key="stock.code"
                closable @close="removeStock(stock)">
          {{ stock.name }}: {{ stock.operate }}
        </el-tag>
      </div>

      <el-button type="primary" @click="submitCorrection">提交修正</el-button>
    </div>
  </div>
</div>
```

---

### Phase 4: 键盘交互实现 (优先级：P1)
**目标**：实现完整的键盘快捷键操作

#### 任务清单
- [ ] 全局键盘事件监听
- [ ] 实现上下键切换消息
- [ ] 实现左右键标记状态
- [ ] 实现Enter跳过逻辑
- [ ] 实现输入模式切换
- [ ] 添加视觉反馈（高亮、动画）

#### 核心代码

```javascript
// 键盘事件处理
function handleKeyPress(e) {
    // 输入模式下禁用快捷键
    if (isInputMode) return;

    switch(e.key) {
        case 'ArrowUp':
            e.preventDefault();
            navigateMessage(-1);
            break;
        case 'ArrowDown':
            e.preventDefault();
            navigateMessage(1);
            break;
        case 'ArrowLeft':
            e.preventDefault();
            markAsCorrect();
            break;
        case 'ArrowRight':
            e.preventDefault();
            markAsWrong();
            break;
        case 'Enter':
            e.preventDefault();
            skipMessage();
            break;
        case 'Escape':
            e.preventDefault();
            exitInputMode();
            break;
    }
}

// 切换到上一条
function navigateMessage(direction) {
    const newIndex = currentIndex + direction;
    if (newIndex >= 0 && newIndex < messages.length) {
        currentIndex = newIndex;
        loadCurrentMessage();
    }
}

// 标记为正确
async function markAsCorrect() {
    const msg = messages[currentIndex];
    // 不做修改，直接下一条
    showToast('已标记为正确', 'success');
    navigateMessage(1);
}

// 标记为错误，进入输入模式
function markAsWrong() {
    reviewStatus = 'wrong';
    isInputMode = true;
    // 自动聚焦到输入框
    nextTick(() => {
        document.querySelector('.stock-input input')?.focus();
    });
}

// 跳过当前消息
function skipMessage() {
    reviewStatus = 'skipped';
    navigateMessage(1);
}

// 提交修正
async function submitCorrection() {
    const msg = messages[currentIndex];

    await fetch('/api/admin/review/correct', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            message_id: msg.id,
            stocks: correctedStocks,
            reviewed_by: getCurrentUser()
        })
    });

    showToast('修正成功', 'success');
    reviewStatus = 'corrected';
    isInputMode = false;
    navigateMessage(1);
}

// 挂载键盘监听
onMounted(() => {
    window.addEventListener('keydown', handleKeyPress);
});

onUnmounted(() => {
    window.removeEventListener('keydown', handleKeyPress);
});
```

---

### Phase 5: 股票联想搜索 (优先级：P2)
**目标**：实现智能股票联想

#### 任务清单
- [ ] 实现前端搜索算法
- [ ] 实现后端搜索API
- [ ] 优化搜索性能
- [ ] 添加防抖处理

#### 搜索算法

```javascript
// 前端搜索实现
import { pinyinMatch } from 'pinyin-pro';

function searchStocks(query, stocks) {
    const q = query.toLowerCase().trim();

    if (!q) return [];

    return stocks.filter(stock => {
        // 1. 代码精确匹配
        if (stock.code === q) return true;

        // 2. 代码前缀匹配
        if (stock.code.startsWith(q)) return true;

        // 3. 名称包含匹配
        if (stock.name.includes(query)) return true;

        // 4. 拼音全拼匹配
        if (stock.pinyin.includes(q)) return true;

        // 5. 首字母匹配
        if (stock.pinyin_abbr.includes(q)) return true;

        // 6. 拼音模糊匹配（连续匹配）
        if (pinyinMatch(stock.name, q)) return true;

        return false;
    }).slice(0, 10); // 限制10条结果
}

// 后端API实现（Python）
@app.route('/api/admin/stocks/search')
def search_stocks():
    query = request.args.get('q', '')

    conn = get_db_connection()
    cursor = conn.cursor()

    # 多条件模糊查询
    cursor.execute("""
        SELECT code, name, pinyin_abbr
        FROM stocks
        WHERE status = 1
          AND (
            code LIKE ?
            OR name LIKE ?
            OR pinyin LIKE ?
            OR pinyin_abbr LIKE ?
          )
        ORDER BY
            CASE WHEN code = ? THEN 1
                 WHEN name = ? THEN 2
                 ELSE 3
            END
        LIMIT 10
    """, (f'{query}%', f'%{query}%', f'{query}%', f'{query}%', query, query))

    results = cursor.fetchall()
    conn.close()

    stocks = [
        {'code': r[0], 'name': r[1], 'pinyin_abbr': r[2]}
        for r in results
    ]

    return jsonify({'success': True, 'stocks': stocks})
```

---

### Phase 6: 测试与优化 (优先级：P3)
**目标**：完善细节，优化体验

#### 任务清单
- [ ] 添加加载状态提示
- [ ] 优化键盘响应速度
- [ ] 添加操作撤销功能
- [ ] 添加批量操作
- [ ] 添加导出功能
- [ ] 性能优化
- [ ] 兼容性测试

---

## 部署清单

### 环境依赖
```bash
# 后端依赖
pip install baostock pypinyin APScheduler

# 前端依赖
npm install vue@3 element-plus @vueuse/core pinyin-pro
```

### 启动顺序
1. **启动后端**：`python3 push_api.py`
2. **访问页面**：`http://localhost:8000/admin/review.html`

### 配置项
```python
# backend/config.json
{
  "stock_sync": {
    "enabled": true,
    "sync_hour": 3,  # 凌晨3点
    "auto_start": true
  }
}
```

---

## 验收标准

### 功能验收
- [ ] 能够筛选频道和日期
- [ ] 键盘操作流畅无延迟
- [ ] 股票联想响应时间 < 200ms
- [ ] 修正数据实时更新到数据库
- [ ] 股票数据每日凌晨3点自动同步
- [ ] 同步日志完整记录

### 性能验收
- [ ] 加载1000条消息 < 2秒
- [ ] 搜索10000只股票 < 100ms
- [ ] 同步5000只股票 < 30秒

### 体验验收
- [ ] 键盘操作有明确视觉反馈
- [ ] 错误提示清晰友好
- [ ] 支持快捷键提示
- [ ] 支持操作撤销

---

## 风险与应对

### 风险1: Baostock API不稳定
**应对**：添加重试机制，失败时使用缓存数据

### 风险2: 拼音匹配不准确
**应对**：结合多种匹配策略，优先显示精确匹配

### 风险3: 键盘事件冲突
**应对**：输入模式下禁用快捷键，添加配置开关

### 风险4: 数据库性能问题
**应对**：添加索引，使用缓存，分页加载

---

## 后续优化方向

1. **智能核对**：基于历史数据自动判断AI准确率
2. **批量操作**：支持批量标记正确/错误
3. **统计分析**：生成AI准确率报告
4. **导入导出**：支持导入修正数据，导出核对报告
5. **权限管理**：不同角色有不同的核对权限

---

## 文档更新记录

- **2026-04-26**: 创建初始方案
- 待补充...

---

**当前状态**: 准备开始Phase 1开发
**下一步**: 实现股票数据同步功能
