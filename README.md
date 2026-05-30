# AKILE Stock Monitor

Telegram 頻道即時補貨監控 Bot。監聽 [@akileStock](https://t.me/akileStock) 頻道，匹配關鍵字後即時通知訂閱用戶。

## 功能

- **即時監聽** — Telethon MTProto 連接，秒級延遲
- **多用戶訂閱** — 用戶自行訂閱/取消關鍵字
- **多通道通知** — Telegram Bot + Bark（iPhone 推送）
- **管理員指令** — 廣播、健康檢查、服務狀態
- **自動備份** — SQLite + session 文件每日備份
- **心跳檢測** — 5 分鐘一次，session 失效自動告警

## Bot 指令

| 指令 | 說明 |
|------|------|
| `/start` | 歡迎 + 使用說明 |
| `/subscribe 關鍵字` | 訂閱型號（支持多個，空格分隔） |
| `/unsubscribe 關鍵字` | 取消訂閱 |
| `/unsuball` | 取消所有訂閱（需二次確認） |
| `/list` | 查看我的訂閱 |
| `/status` | 服務狀態 + 熱門關鍵字 |
| `/health` | 健康檢查（僅管理員） |
| `/broadcast 消息` | 廣播（僅管理員） |

## 部署

### 1. 申請 Telegram API

前往 [my.telegram.org](https://my.telegram.org) → API development tools → Create new application，獲取 `api_id` 和 `api_hash`。

### 2. 創建 Telegram Bot

在 Telegram 中找 [@BotFather](https://t.me/BotFather)，發送 `/newbot`，獲取 bot token。

### 3. 本地授權

```bash
pip install telethon requests
cp config.example.json config.json
# 編輯 config.json 填入你的配置
python3 step1.py   # 發送驗證碼
python3 sign_in.py # 輸入驗證碼完成登入
```

### 4. 部署到服務器

```bash
# 上傳項目
scp -r . root@your-server:~/akile-monitor

# SSH 到服務器
ssh root@your-server
cd ~/akile-monitor

# 安裝依賴
pip3 install telethon requests

# 配置 systemd
cp akile-monitor.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable akile-monitor
systemctl start akile-monitor
```

### 5. 設置備份

```bash
# 添加每日 4am 備份 cron
echo "0 4 * * * /root/akile-monitor/backup.sh >> /root/akile-monitor/backup.log 2>&1" | crontab -
```

## 項目結構

```
akile-monitor/
├── monitor.py              # 主程序（Telethon 監聽 + 心跳 + 通知）
├── bot.py                  # Bot 指令處理（async poll loop）
├── db.py                   # SQLite 數據庫層
├── config.json             # 配置文件（git ignored）
├── config.example.json     # 配置模板
├── akile-monitor.service   # systemd 服務文件
├── backup.sh               # 備份腳本
├── Dockerfile              # Docker 部署（可選）
└── docker-compose.yml
```

## 配置說明

編輯 `config.json`：

```json
{
  "telegram": {
    "api_id": 12345,
    "api_hash": "your_api_hash",
    "session_name": "akile_monitor"
  },
  "monitor": {
    "channel": "akileStock",
    "keywords": ["Pro"]
  },
  "notify": {
    "bark_url": "https://your-bark-server/key",
    "bark_sound": "multiwayinvitation",
    "tg_bot_token": "123456:ABC...",
    "tg_chat_id": "your_chat_id"
  }
}
```

- `keywords` — 管理員自動訂閱的初始關鍵字
- `bark_url` — Bark 推送地址（可選）
- `tg_chat_id` — 管理員的 Telegram chat_id

## 備份與恢復

### 自動備份

- **本地備份**: oracle2 每日 4am 備份到 `/root/akile-monitor/backups/`，保留 7 天
- **R2 備份**: 同步上傳到 Cloudflare R2，保留 30 天
  - 路徑: `backups/akile-monitor/subscriptions_YYYYMMDD_HHMM.db`
  - 最新副本: `backups/akile-monitor/latest/subscriptions.db`

### 從 R2 恢復

```bash
# 安裝 aws cli (S3 兼容)
pip3 install boto3

# 下載最新備份
python3 -c "
import boto3, json
with open('r2.json') as f:
    r2 = json.load(f)
s3 = boto3.client('s3',
    endpoint_url=f'https://{r2[\"account_id\"]}.r2.cloudflarestorage.com',
    aws_access_key_id=r2['access_key'],
    aws_secret_access_key=r2['secret_key'],
    region_name='auto')
s3.download_file(r2['bucket'], 'backups/akile-monitor/latest/subscriptions.db', 'data/subscriptions.db')
s3.download_file(r2['bucket'], 'backups/akile-monitor/latest/akile_monitor.session', 'session/akile_monitor.session')
print('Restored!')
"

# 重啟服務
systemctl restart akile-monitor
```

### 從本地備份恢復

```bash
# 找最近的備份
ls -lt /root/akile-monitor/backups/

# 恢復
cp /root/akile-monitor/backups/subscriptions_LATEST.db /root/akile-monitor/data/subscriptions.db
cp /root/akile-monitor/backups/session_LATEST.session /root/akile-monitor/session/akile_monitor.session
systemctl restart akile-monitor
```

## License

MIT
