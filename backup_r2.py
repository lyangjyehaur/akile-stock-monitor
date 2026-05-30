#!/usr/bin/env python3
"""Backup AKILE monitor data to Cloudflare R2."""
import os
import sys
import json
import glob
from datetime import datetime
from pathlib import Path

try:
    import boto3
except ImportError:
    print("boto3 not installed, run: pip3 install boto3")
    sys.exit(1)

# Config
DATA_DIR = Path("/root/akile-monitor/data")
SESSION_DIR = Path("/root/akile-monitor/session")
LOCAL_BACKUP = Path("/root/akile-monitor/backups")
R2_PREFIX = "backups/akile-monitor"

# R2 credentials
R2_CFG = Path(__file__).parent / "r2.json"
with open(R2_CFG) as f:
    r2 = json.load(f)

ENDPOINT = f"https://{r2['account_id']}.r2.cloudflarestorage.com"
BUCKET = r2["bucket"]


def upload_file(s3, local_path: Path, key: str):
    if not local_path.exists():
        print(f"  skip (not found): {local_path}")
        return
    s3.upload_file(str(local_path), BUCKET, key)
    size = local_path.stat().st_size
    print(f"  uploaded: {key} ({size} bytes)")


def main():
    date = datetime.now().strftime("%Y%m%d_%H%M")

    # Local backup first
    LOCAL_BACKUP.mkdir(parents=True, exist_ok=True)
    db_src = DATA_DIR / "subscriptions.db"
    sess_src = SESSION_DIR / "akile_monitor.session"

    db_local = LOCAL_BACKUP / f"subscriptions_{date}.db"
    sess_local = LOCAL_BACKUP / f"session_{date}.session"

    if db_src.exists():
        import shutil
        shutil.copy2(db_src, db_local)
    if sess_src.exists():
        import shutil
        shutil.copy2(sess_src, sess_local)

    # Clean old local backups (keep 7 days)
    for pattern in ["*.db", "*.session"]:
        for f in LOCAL_BACKUP.glob(pattern):
            if f.stat().st_mtime < datetime.now().timestamp() - 7 * 86400:
                f.unlink()

    # Upload to R2
    print(f"Uploading to R2: {BUCKET}/{R2_PREFIX}/")
    s3 = boto3.client(
        "s3",
        endpoint_url=ENDPOINT,
        aws_access_key_id=r2["access_key"],
        aws_secret_access_key=r2["secret_key"],
        region_name="auto",
    )

    upload_file(s3, db_src, f"{R2_PREFIX}/subscriptions_{date}.db")
    upload_file(s3, sess_src, f"{R2_PREFIX}/session_{date}.session")

    # Also upload latest as "current" for easy restore
    upload_file(s3, db_src, f"{R2_PREFIX}/latest/subscriptions.db")
    upload_file(s3, sess_src, f"{R2_PREFIX}/latest/akile_monitor.session")

    # Clean old R2 backups (keep 30 days)
    cutoff = datetime.now().timestamp() - 30 * 86400
    try:
        resp = s3.list_objects_v2(Bucket=BUCKET, Prefix=f"{R2_PREFIX}/subscriptions_")
        deleted = 0
        for obj in resp.get("Contents", []):
            if obj["LastModified"].timestamp() < cutoff:
                s3.delete_object(Bucket=BUCKET, Key=obj["Key"])
                deleted += 1
        if deleted:
            print(f"  cleaned {deleted} old R2 backups")
    except Exception as e:
        print(f"  R2 cleanup warning: {e}")

    print(f"Backup done: {date}")


if __name__ == "__main__":
    main()
