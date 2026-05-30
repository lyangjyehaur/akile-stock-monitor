#!/usr/bin/env python3
"""
AKILE Stock Monitor — multi-user Telegram channel monitor.

Telethon listens to @akileStock in real-time.
Bot API handles user subscriptions (/subscribe, /list, etc).
When a message matches, all matching subscribers get notified.
"""

import json
import logging
from pathlib import Path
from urllib.parse import quote

import requests
from telethon import TelegramClient, events

from db import db
from bot import bot_poll_loop

# ── Logging ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("akile-monitor")

# ── Config ───────────────────────────────────────────────
CONFIG_PATH = Path(__file__).parent / "config.json"


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


cfg = load_config()

API_ID = cfg["telegram"]["api_id"]
API_HASH = cfg["telegram"]["api_hash"]
SESSION_DIR = Path(__file__).parent / "session"
SESSION_DIR.mkdir(exist_ok=True)
SESSION = str(SESSION_DIR / cfg["telegram"]["session_name"])
CHANNEL = cfg["monitor"]["channel"]

BARK_URL = cfg["notify"]["bark_url"].rstrip("/")
BARK_SOUND = cfg["notify"].get("bark_sound", "multiwayinvitation")
BOT_TOKEN = cfg["notify"]["tg_bot_token"]
ADMIN_CHAT_ID = int(cfg["notify"]["tg_chat_id"])

# ── Telethon client ─────────────────────────────────────
client = TelegramClient(SESSION, API_ID, API_HASH)


# ── Notification helpers ─────────────────────────────────
def notify_bark(title: str, body: str, url: str = None):
    """Send push notification via Bark (admin only)."""
    if not BARK_URL:
        return
    notify_bark_url(BARK_URL, title, body, url)


def notify_bark_url(bark_url: str, title: str, body: str, url: str = None):
    """Send push notification via a specific Bark URL."""
    bark_url = bark_url.rstrip("/")
    encoded_title = quote(title, safe="")
    encoded_body = quote(body, safe="")
    bark_endpoint = f"{bark_url}/{encoded_title}/{encoded_body}"
    params = {"sound": BARK_SOUND}
    if url:
        params["url"] = url
    try:
        resp = requests.get(bark_endpoint, params=params, timeout=10)
        if resp.status_code == 200:
            log.info("Bark sent to %s", bark_url[:30])
        else:
            log.warning("Bark failed (%d) for %s", resp.status_code, bark_url[:30])
    except Exception as e:
        log.error("Bark error for %s: %s", bark_url[:30], e)


def notify_telegram(chat_id: int, text: str, button_url: str = None) -> bool:
    """Send message to a specific user via Bot API. Optionally attach an inline button."""
    if not BOT_TOKEN:
        return False
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if button_url:
        payload["reply_markup"] = json.dumps({
            "inline_keyboard": [[{"text": "立即下單", "url": button_url}]]
        })
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json=payload,
            timeout=10,
        )
        if resp.status_code == 200:
            return True
        else:
            log.warning("TG notify failed for %s (%d)", chat_id, resp.status_code)
            return False
    except Exception as e:
        log.error("TG notify error for %s: %s", chat_id, e)
        return False


def extract_product_name(text: str) -> str:
    """Try to extract product name from message text."""
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        for prefix in ["库存增加：", "库存增加:"]:
            if line.startswith(prefix):
                line = line[len(prefix):].strip()
        return line.split()[0] if line.split() else text[:50]
    return text[:50]


@client.on(events.NewMessage(chats=CHANNEL))
async def handler(event):
    text = event.raw_text or ""
    text_lower = text.lower()

    # Get all subscriptions from DB
    subs_map = db.get_all_subscriptions_map()
    if not subs_map:
        return

    # Find matching keywords
    matched_keywords = set()
    for kw in subs_map:
        if kw in text_lower:
            matched_keywords.add(kw)

    if not matched_keywords:
        return

    product = extract_product_name(text)
    log.info("MATCH! product=%s keywords=%s", product, matched_keywords)

    # Extract order URL from inline buttons
    order_url = None
    if event.message.buttons:
        for row in event.message.buttons:
            for btn in row:
                if btn.url:
                    order_url = btn.url
                    break
            if order_url:
                break

    # Collect all unique chat_ids to notify
    notified = set()
    for kw in matched_keywords:
        for chat_id in subs_map[kw]:
            notified.add(chat_id)

    # Send Telegram notifications with rate limiting
    tg_msg = (
        f"<b>AKILE 補貨通知</b>\n\n"
        f"<b>產品:</b> {product}\n"
        f"<b>匹配:</b> {', '.join(matched_keywords)}"
    )
    notified_count = 0
    # Get all Bark URLs for matching users
    all_bark = db.get_all_bark_urls()
    for chat_id in notified:
        if notify_telegram(chat_id, tg_msg, button_url=order_url):
            notified_count += 1
        # Send Bark to user if they set one
        user_bark = all_bark.get(chat_id)
        if user_bark:
            notify_bark_url(user_bark, "AKILE 補貨！", f"{product}", url=order_url)
        # Telegram rate limit: ~30 msg/sec, we stay safe at ~20/sec
        await asyncio.sleep(0.05)

    # Bark for admin
    bark_body = f"{product} 補貨！"
    if order_url:
        bark_body += f"\n{order_url}"
    notify_bark("AKILE 補貨！", bark_body, url=order_url)

    log.info("Notified %d users", len(notified))


async def health_check_loop():
    """Periodically check Telethon session health. Alert admin if broken."""
    consecutive_failures = 0
    while True:
        await asyncio.sleep(300)  # every 5 minutes
        try:
            if not client.is_connected():
                consecutive_failures += 1
                log.warning("Health check: client disconnected! attempt=%d", consecutive_failures)
                if consecutive_failures >= 2:
                    notify_bark("AKILE 監控斷線！", "Telethon 連接已斷開，正在嘗試重連...")
                    notify_telegram(ADMIN_CHAT_ID, "<b>監控告警</b>\nTelethon 連接斷開，正在重連...\n\n聯繫管理員：@DanersAka")
                try:
                    await client.connect()
                    me = await client.get_me()
                    log.info("Reconnected as %s", me.first_name)
                    consecutive_failures = 0
                except Exception as re:
                    log.error("Reconnect failed: %s", re)
            else:
                # Deep check: actually call the API
                me = await client.get_me()
                if not me:
                    raise Exception("get_me returned None")
                consecutive_failures = 0
        except Exception as e:
            consecutive_failures += 1
            log.warning("Health check failed: %s (attempt=%d)", e, consecutive_failures)
            if consecutive_failures >= 3:
                notify_bark("AKILE 監控失效！", f"監聽連線可能已過期，錯誤: {e}")
                notify_telegram(ADMIN_CHAT_ID,
                    f"<b>監控嚴重告警</b>\n\n"
                    f"頻道監聽連線失效，連續 {consecutive_failures} 次檢查失敗。\n"
                    f"錯誤: <code>{e}</code>\n\n"
                    f"需要重新授權監聽帳號。\n\n"
                    f"聯繫管理員：@DanersAka")


async def main():
    log.info("Starting AKILE Stock Monitor (multi-user)")

    # Auto-subscribe admin to initial keywords from config
    initial_kw = cfg["monitor"].get("keywords", [])
    if initial_kw:
        db.upsert_user(ADMIN_CHAT_ID, first_name="Admin")
        db.set_admin(ADMIN_CHAT_ID, True)
        for kw in initial_kw:
            db.add_subscription(ADMIN_CHAT_ID, kw)
        log.info("Admin auto-subscribed to: %s", initial_kw)

    # Auto-set admin's Bark URL from config
    if BARK_URL:
        db.upsert_user(ADMIN_CHAT_ID)
        db.set_bark_url(ADMIN_CHAT_ID, BARK_URL)
        log.info("Admin Bark URL synced from config")

    # Connect Telethon
    await client.connect()
    me = await client.get_me()
    log.info("Logged in as: %s (id=%s)", me.first_name, me.id)
    log.info("Monitoring channel: @%s", CHANNEL)
    log.info("Bot token: %s", "configured" if BOT_TOKEN else "NOT SET")
    log.info("Admin chat_id: %s", ADMIN_CHAT_ID)
    log.info("Waiting for restock messages...")

    # Run Telethon monitor + bot poll loop + health check concurrently
    tasks = [
        client.run_until_disconnected(),
        health_check_loop(),
    ]
    if BOT_TOKEN:
        tasks.append(bot_poll_loop(BOT_TOKEN, ADMIN_CHAT_ID))
        log.info("Bot poll loop task added")
    log.info("Health check loop added (every 5min)")

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    import asyncio
    client.loop.run_until_complete(main())
