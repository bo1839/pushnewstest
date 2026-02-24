# Feishu News Bot

每日自动采集 IT、金融、AI 行业新闻，调用 DeepSeek AI 总结，推送到飞书群聊。

## 功能特性

- 🤖 自动采集多个新闻源
- 🧠 使用 DeepSeek API 智能总结关键事件
- 📱 每日早上 8:00 自动推送到飞书
- 💰 零成本运行（GitHub Actions + DeepSeek 免费额度）

## 快速开始

### 1. 准备配置

复制环境变量文件并填写配置：

```bash
cp .env.example .env
```

编辑 `.env` 文件，填入以下配置：

```env
DEEPSEEK_API_KEY=sk-xxxxxxx
FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

### 2. 本地测试

```bash
pip install -r requirements.txt
python main.py
```

### 3. 部署到 GitHub Actions

1. 将代码推送到 GitHub 仓库
2. 在仓库 Settings → Secrets and variables → Actions 中添加：
   - `DEEPSEEK_API_KEY`: 你的 DeepSeek API Key
   - `FEISHU_WEBHOOK_URL`: 你的飞书 Webhook URL
3. 每天早上 8:00（北京时间）自动运行

## 新闻源

| 类别 | 来源 |
|------|------|
| IT | 36Kr 科技 |
| IT | IT之家 |
| IT | 虎嗅 |

## 成本估算

- **GitHub Actions**: 免费（每月 2000 分钟）
- **DeepSeek API**: 约 ¥0.01-0.05/月
- **飞书**: 免费

## 许可证

MIT License
