#!/bin/bash
# Watchdog: check if akile-monitor is running, restart + alert if not
SERVICE="akile-monitor"
BOT_TOKEN=$(python3 -c "import json; print(json.load(open('/root/akile-monitor/config.json'))['notify']['tg_bot_token'])" 2>/dev/null)
CHAT_ID=$(python3 -c "import json; print(json.load(open('/root/akile-monitor/config.json'))['notify']['tg_chat_id'])" 2>/dev/null)

if systemctl is-active --quiet "$SERVICE"; then
    # Service running, check if process is responsive
    PID=$(systemctl show -p MainPID "$SERVICE" --value)
    if [ "$PID" != "0" ] && [ -d "/proc/$PID" ]; then
        exit 0
    fi
fi

# Service is down, restart
echo "$(date): $SERVICE is down, restarting..."
systemctl restart "$SERVICE"
sleep 5

if systemctl is-active --quiet "$SERVICE"; then
    MSG="akile-monitor 已自動重啟恢復"
else
    MSG="akile-monitor 自動重啟失敗，需要人工介入！\n聯繫管理員：@DanersAka"
fi

# Notify via Telegram Bot API
if [ -n "$BOT_TOKEN" ] && [ -n "$CHAT_ID" ]; then
    curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
        -H "Content-Type: application/json" \
        -d "{\"chat_id\": ${CHAT_ID}, \"text\": \"[Watchdog] ${MSG}\", \"parse_mode\": \"HTML\"}" \
        > /dev/null 2>&1
fi

echo "$(date): $MSG"
