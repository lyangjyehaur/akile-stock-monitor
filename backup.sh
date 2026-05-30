#!/bin/bash
# Backup AKILE monitor data (SQLite + session)
BACKUP_DIR=/root/akile-monitor/backups
mkdir -p $BACKUP_DIR
DATE=$(date +%Y%m%d_%H%M)

# SQLite backup (safe copy)
cp /root/akile-monitor/data/subscriptions.db $BACKUP_DIR/subscriptions_${DATE}.db 2>/dev/null

# Session backup
cp /root/akile-monitor/session/akile_monitor.session $BACKUP_DIR/session_${DATE}.session 2>/dev/null

# Keep last 7 days
find $BACKUP_DIR -name '*.db' -mtime +7 -delete 2>/dev/null
find $BACKUP_DIR -name '*.session' -mtime +7 -delete 2>/dev/null

echo "Backup done: $DATE"
