# AKILE Stock Monitor

Telegram 頻道即時補貨監控 Bot。監聽 [@akileStock](https://t.me/akileStock) 頻道，匹配關鍵字後即時通知訂閱用戶。

## 功能

- **即時監聽** — Telethon MTProto 連接，秒級延遲
- **多用戶訂閱** — 用戶自行訂閱/取消關鍵字
- **多通道通知** — Telegram Bot + Bark（iPhone 推送）
- **管理員指令** — 廣播、健康檢查、數據查看
- **自動備份** — SQLite + session 文件每日備份到 Cloudflare R2
- **心跳檢測** — 5 分鐘一次，session 失效自動告警
- **進程監控** — watchdog 每 5 分鐘檢查，掛了自動重啟
- **異步架構** — python-telegram-bot v20+ 框架，Telethon 與 Bot 共用 event loop

## Bot 指令

### 用戶指令

| 指令 | 縮寫 | 說明 |
|------|------|------|
| `/start` | — | 歡迎頁面 + 使用說明 |
| `/help` | — | 顯示使用說明 |
| `/subscribe 關鍵字` | `/sub` | 訂閱型號（支持多個，空格分隔） |
| `/unsubscribe 關鍵字` | `/unsub` | 取消訂閱 |
| `/unsuball` | — | 取消所有訂閱（需二次確認，60 秒內重複發送） |
| `/list` | — | 查看我的訂閱列表 |
| `/me` | — | 查看個人資料、訂閱數、Bark 狀態 |
| `/keywords` | — | 查看所有熱門關鍵字及訂閱人數 |
| `/bark URL` | — | 設定 Bark 推送（iPhone 用戶） |
| `/bark off` | — | 取消 Bark 推送 |
| `/bark` | — | 查看當前 Bark 設定 |
| `/status` | — | 查看服務運行狀態、用戶數、訂閱數、近 24h 統計 |

### 管理員指令

管理員由 `config.json` 中的 `tg_chat_id` 決定，只有該用戶可使用以下指令。

| 指令 | 說明 |
|------|------|
| `/health` | 健康檢查（Bot API、頻道監聽、心跳狀態） |
| `/broadcast 消息` | 向所有用戶發送公告（帶限速） |
| `/users` | 查看所有用戶列表（訂閱數、Bark 狀態） |
| `/recent` | 查看最近 10 條補貨事件記錄 |
| `/top` | 查看關鍵字訂閱人數排行 + 近 24h 補貨事件數 |
| `/user chat_id` | 查看特定用戶詳情（訂閱列表、Bark、註冊時間） |

## 部署

### 1. 申請 Telegram API

前往 [my.telegram.org](https://my.telegram.org) → API development tools → Create new application，獲取 `api_id` 和 `api_hash`。

### 2. 創建 Telegram Bot

在 Telegram 中找 [@BotFather](https://t.me/BotFather)，發送 `/newbot`，獲取 bot token。

### 3. 配置

```bash
cp config.example.json config.json
# 編輯 config.json 填入你的配置
```

### 4. Telethon 授權

在服務器上執行（需要交互輸入手機號和驗證碼）：

```bash
pip3 install telethon requests "python-telegram-bot>=20,<22" boto3
python3 step1.py   # 發送驗證碼
python3 sign_in.py # 輸入驗證碼完成登入
```

### 5. 部署服務

```bash
# 配置 systemd
cp akile-monitor.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable akile-monitor
systemctl start akile-monitor

# 設置 watchdog cron（每 5 分鐘檢查進程）
echo "*/5 * * * * /root/akile-monitor/watchdog.sh >> /root/akile-monitor/watchdog.log 2>&1" | crontab -

# 設置 R2 備份 cron（每日 4am）
(crontab -l; echo "0 4 * * * cd /root/akile-monitor && python3 backup_r2.py >> /root/akile-monitor/backup.log 2>&1") | crontab -
```

## 項目結構

```
akile-monitor/
├── monitor.py              # 主程序（Telethon 監聽 + 心跳 + 通知）
├── bot.py                  # Bot 指令處理（python-telegram-bot 框架）
├── db.py                   # SQLite 數據庫層
├── config.json             # 配置文件（git ignored）
├── config.example.json     # 配置模板
├── r2.json                 # R2 憑證（git ignored）
├── akile-monitor.service   # systemd 服務文件
├── backup_r2.py            # R2 備份腳本
├── backup.sh               # 本地備份腳本
├── watchdog.sh             # 進程監控腳本
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

- `keywords` — 管理員自動訂閱的初始關鍵字（服務重啟生效）
- `bark_url` — 管理員的 Bark 推送地址（可選）
- `tg_chat_id` — 管理員的 Telegram chat_id（決定誰是管理員）
- `bark_sound` — Bark 推送鈴聲

## 關鍵字訂閱規則

- 最短 2 個字符，最長 50 個字符
- 不分大小寫，頻道消息中包含即觸發
- 每人最多 20 個訂閱
- 過短的關鍵字（如 "HK"、"SG"）可能匹配大量產品，建議訂閱精準關鍵字

## 通知通道

訂閱用戶可通過以下通道接收補貨通知：

1. **Telegram 私訊** — 所有訂閱用戶自動接收
2. **Bark 推送** — 用戶自行設定（`/bark URL`），直接彈到 iPhone 鎖屏
3. **管理員 Bark** — 從 `config.json` 讀取，每次補貨都會收到

通知消息包含產品名稱和「立即下單」按鈕，點擊直接跳轉到下單頁面。

## 備份與恢復

### 自動備份

- **本地備份**: 每日 4am 備份到 `/root/akile-monitor/backups/`，保留 7 天
- **R2 備份**: 同步上傳到 Cloudflare R2，保留 30 天
  - 路徑: `backups/akile-monitor/subscriptions_YYYYMMDD_HHMM.db`
  - 最新副本: `backups/akile-monitor/latest/subscriptions.db`
- **進程監控**: watchdog 每 5 分鐘檢查，掛了自動重啟 + Telegram 通知管理員

### 從 R2 恢復

```bash
pip3 install boto3

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

systemctl restart akile-monitor
```

### 從本地備份恢復

```bash
ls -lt /root/akile-monitor/backups/

cp /root/akile-monitor/backups/subscriptions_LATEST.db /root/akile-monitor/data/subscriptions.db
cp /root/akile-monitor/backups/session_LATEST.session /root/akile-monitor/session/akile_monitor.session
systemctl restart akile-monitor
```

## License

MIT
