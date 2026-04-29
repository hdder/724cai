# 724 财讯消息推送接口文档

## 一、接口说明

本文档用于外部程序将消息推送到 724 财讯平台，消息会实时展示在平台网页端对应频道内。

**接口风格：** 兼容主流机器人格式（易于对接）

## 二、基础信息

### 请求地址
```
POST http://111.228.8.17:5555/push/send?channel_token=频道对应的token
```

或本地测试：
```
POST http://localhost:5555/push/send?channel_token=频道对应的token
```

### 请求方式
- Method: `POST`
- Content-Type: `application/json`

## 三、权限说明

`channel_token` 即频道唯一标识：
- 一个 token 对应一个接收频道
- 由平台管理员分配
- 调用时放在 URL 参数中

## 四、请求体格式（固定）

```json
{
  "msgtype": "markdown",
  "markdown": {
    "title": "消息标题",
    "text": "消息内容（支持 Markdown）"
  }
}
```

## 五、支持的消息类型

### 1. 纯文本
```json
{
  "msgtype": "markdown",
  "markdown": {
    "title": "系统通知",
    "text": "这是一条普通文本消息"
  }
}
```

### 2. 多行文本 & 列表
```json
{
  "msgtype": "markdown",
  "markdown": {
    "title": "今日预判",
    "text": "今日思路：\n- 高开不追\n- 回踩企稳接\n- 破位直接放弃"
  }
}
```

### 3. 图片
```json
{
  "msgtype": "markdown",
  "markdown": {
    "title": "行情截图",
    "text": "![分析图](https://example.com/image.jpg)"
  }
}
```

### 4. 链接
```json
{
  "msgtype": "markdown",
  "markdown": {
    "title": "资料链接",
    "text": "[查看详细公告](https://www.example.com)"
  }
}
```

### 5. 混合富文本（最常用）
```json
{
  "msgtype": "markdown",
  "markdown": {
    "title": "综合推送",
    "text": "# 重要提示\n**当前位置：支撑区**\n![图示](https://example.com/image.jpg)\n[详情点击](https://www.example.com)"
  }
}
```

## 六、响应格式

### 成功响应
```json
{
  "code": 0,
  "message": "success"
}
```

### 失败响应

**无效的 channel_token**
```json
{
  "code": 401,
  "message": "无效的 channel_token"
}
```

**参数格式错误**
```json
{
  "code": 400,
  "message": "参数格式错误"
}
```

**服务器处理异常**
```json
{
  "code": 500,
  "message": "服务器处理异常"
}
```

## 七、调用示例

### curl 示例
```bash
curl -X POST "http://111.228.8.17:5555/push/send?channel_token=YOUR_TOKEN" \
-H "Content-Type: application/json" \
-d '{
  "msgtype": "markdown",
  "markdown": {
    "title": "今日预判",
    "text": "思路完全正确，继续持有"
  }
}'
```

### Python 示例
```python
import requests
import json

url = "http://111.228.8.17:5555/push/send?channel_token=YOUR_TOKEN"
payload = {
    "msgtype": "markdown",
    "markdown": {
        "title": "今日预判",
        "text": "思路完全正确，继续持有"
    }
}

response = requests.post(url, json=payload)
print(response.json())
```

### JavaScript 示例
```javascript
fetch('http://111.228.8.17:5555/push/send?channel_token=YOUR_TOKEN', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    msgtype: 'markdown',
    markdown: {
      title: '今日预判',
      text: '思路完全正确，继续持有'
    }
  })
})
.then(response => response.json())
.then(data => console.log(data));
```

## 八、获取 Token

Token 在管理后台自动生成并显示：

1. 访问管理后台：http://111.228.8.17:8000/admin.html?admin_token=724caixun_admin_2024_k9HxM7qL
2. 每个频道会自动生成唯一的 Token
3. 点击"复制"按钮复制 Token
4. 使用 Token 调用推送接口

## 九、注意事项

1. ✅ 图片 URL 必须为公网可访问地址
2. ✅ 换行使用 `\n`
3. ✅ 消息会实时推送到网页前端对应频道
4. ✅ 消息会保存到数据库，刷新页面不丢失
5. ⚠️ 接口仅用于对接程序调用，不支持浏览器直接访问表单
6. ⚠️ 请确保服务器防火墙开放 5555 端口

## 十、测试步骤

### 本地测试

1. 启动服务：
   ```bash
   cd /Users/hesiyuan/Code/724caixun
   ./start.sh
   ```

2. 打开前端页面：http://localhost:8000

3. 运行测试命令：
   ```bash
   curl -X POST "http://localhost:5555/push/send?channel_token=YOUR_TOKEN" \
   -H "Content-Type: application/json" \
   -d '{"msgtype":"markdown","markdown":{"title":"测试消息","text":"这是一条测试消息"}}'
   ```

4. 前端应该能实时看到消息弹出

### 服务器测试

1. 确认服务已启动（访问管理后台）

2. 使用服务器 IP 测试：
   ```bash
   curl -X POST "http://111.228.8.17:5555/push/send?channel_token=YOUR_TOKEN" \
   -H "Content-Type: application/json" \
   -d '{"msgtype":"markdown","markdown":{"title":"测试消息","text":"这是一条测试消息"}}'
   ```

3. 前端页面应该能实时收到消息

## 十一、联系支持

如有问题，请联系平台管理员。
