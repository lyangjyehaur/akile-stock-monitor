#!/bin/bash
# Pull AKILE monitor backups from oracle2 to local Mac
LOCAL_DIR="$HOME/Projects/akile-monitor/backups"
REMOTE="oracle2:~/akile-monitor/data/subscriptions.db"
REMOTE_SESSION="oracle2:~/akile-monitor/session/akile_monitor.session"
DATE=$(date +%Y%m%d)

mkdir -p "$LOCAL_DIR"

# Pull SQLite
scp -P 4649 root@140.83.36.24:~/akile-monitor/data/subscriptions.db "$LOCAL_DIR/subscriptions_${DATE}.db" 2>/dev/null

# Pull session
scp -P 4649 root@140.83.36.24:~/akile-monitor/session/akile_monitor.session "$LOCAL_DIR/session_${DATE}.session" 2>/dev/null

# Keep last 30 days locally
find "$LOCAL_DIR" -name '*.db' -mtime +30 -delete 2>/dev/null
find "$LOCAL_DIR" -name '*.session' -mtime +30 -delete 2>/dev/null

echo "Backup pulled: $DATE"
