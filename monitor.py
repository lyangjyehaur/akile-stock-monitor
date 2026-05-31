#!/usr/bin/env python3
"""
AKILE Stock Monitor — polling-based channel monitor.
Checks @akileStock every 10 seconds for new messages.
Simpler and more reliable than Telethon event handler.
"""

import asyncio
import json
import logging
import threading
import time
from pathlib import Path
from urllib.parse import quote

import requests
from telethon import TelegramClient

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
POLL_INTERVAL = 10  # seconds

BARK_URL = cfg["notify"]["bark_url"].rstrip("/")
BARK_SOUND = cfg["notify"].get("bark_sound", "multiwayinvitation")
BOT_TOKEN = cfg["notify"]["tg_bot_token"]
ADMIN_CHAT_ID = int(cfg["notify"]["tg_chat_id"])

# ── Telethon client ─────────────────────────────────────
client = TelegramClient(SESSION, API_ID, API_HASH)


# ── Notification helpers ─────────────────────────────────
def notify_bark(title: str, body: str, url: str = None):
    if not BARK_URL:
        return
    notify_bark_url(BARK_URL, title, body, url)


def notify_bark_url(bark_url: str, title: str, body: str, url: str = None):
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
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        for prefix in ["库存增加：", "库存增加:"]:
            if line.startswith(prefix):
                line = line[len(prefix):].strip()
        return line.split()[0] if line.split() else text[:50]
    return text[:50]


# ── Polling monitor ──────────────────────────────────────
async def poll_channel():
    """Poll @akileStock for new messages and notify subscribers."""
    log.info("Polling monitor started (interval=%ds)", POLL_INTERVAL)

    # Get the latest message ID as baseline (don't notify for old messages)
    try:
        msgs = await client.get_messages(CHANNEL, limit=1)
        last_seen_id = msgs[0].id if msgs else 0
        log.info("Baseline: last message id=%d", last_seen_id)
    except Exception as e:
        log.error("Failed to get baseline: %s", e)
        last_seen_id = 0

    while True:
        await asyncio.sleep(POLL_INTERVAL)
        try:
            # Fetch messages newer than last_seen_id
            messages = await client.get_messages(
                CHANNEL, min_id=last_seen_id, limit=20
            )

            if not messages:
                continue

            # Process new messages (oldest first)
            for msg in reversed(messages):
                if msg.id <= last_seen_id:
                    continue

                last_seen_id = msg.id
                text = msg.raw_text or ""
                text_lower = text.lower()

                # Check keyword match
                subs_map = db.get_all_subscriptions_map()
                if not subs_map:
                    continue

                matched_keywords = set()
                for kw in subs_map:
                    if kw in text_lower:
                        matched_keywords.add(kw)

                if not matched_keywords:
                    log.info("New msg id=%d but no match: %s", msg.id, text[:50])
                    continue

                product = extract_product_name(text)
                log.info("MATCH! id=%d product=%s keywords=%s", msg.id, product, matched_keywords)

                # Extract order URL
                order_url = None
                if msg.buttons:
                    for row in msg.buttons:
                        for btn in row:
                            if btn.url:
                                order_url = btn.url
                                break
                        if order_url:
                            break

                # Collect subscribers
                notified = set()
                for kw in matched_keywords:
                    for chat_id in subs_map[kw]:
                        notified.add(chat_id)

                # Send notifications
                tg_msg = (
                    f"<b>AKILE 補貨通知</b>\n\n"
                    f"<b>產品:</b> {product}\n"
                    f"<b>匹配:</b> {', '.join(matched_keywords)}\n\n"
                    f"<pre>{text.strip()}</pre>"
                )
                notified_count = 0
                all_bark = db.get_all_bark_urls()
                for chat_id in notified:
                    if notify_telegram(chat_id, tg_msg, button_url=order_url):
                        notified_count += 1
                    user_bark = all_bark.get(chat_id)
                    if user_bark:
                        notify_bark_url(user_bark, "AKILE 補貨！", product, order_url)
                    await asyncio.sleep(0.05)

                # Bark for admin
                bark_body = f"{product} 補貨！"
                if order_url:
                    bark_body += f"\n{order_url}"
                notify_bark("AKILE 補貨！", bark_body, url=order_url)

                log.info("Notified %d users for %s", notified_count, product)

                # Log event
                db.log_restock_event(
                    product=product,
                    matched_kw=", ".join(matched_keywords),
                    order_url=order_url or "",
                    notified=notified_count,
                )

        except Exception as e:
            log.error("Poll error: %s", e)
            await asyncio.sleep(5)


# ── Health check ─────────────────────────────────────────
async def health_check_loop():
    consecutive_failures = 0
    while True:
        await asyncio.sleep(300)
        try:
            if not client.is_connected():
                consecutive_failures += 1
                log.warning("Health check: disconnected! attempt=%d", consecutive_failures)
                if consecutive_failures >= 2:
                    notify_bark("AKILE 監控斷線！", "正在嘗試重連...")
                    notify_telegram(ADMIN_CHAT_ID, "<b>監控告警</b>\n連接斷開，正在重連...\n\n聯繫管理員：@DanersAka")
                try:
                    await client.connect()
                    me = await client.get_me()
                    log.info("Reconnected as %s", me.first_name)
                    consecutive_failures = 0
                except Exception as re:
                    log.error("Reconnect failed: %s", re)
            else:
                me = await client.get_me()
                if not me:
                    raise Exception("get_me returned None")
                consecutive_failures = 0
                try:
                    db._get_conn().execute("PRAGMA wal_checkpoint(PASSIVE)")
                except Exception:
                    pass
        except Exception as e:
            consecutive_failures += 1
            log.warning("Health check failed: %s (attempt=%d)", e, consecutive_failures)
            if consecutive_failures >= 3:
                notify_bark("AKILE 監控失效！", f"錯誤: {e}")
                notify_telegram(
                    ADMIN_CHAT_ID,
                    f"<b>監控嚴重告警</b>\n\n連續 {consecutive_failures} 次失敗。\n錯誤: <code>{e}</code>\n\n聯繫管理員：@DanersAka",
                )


# ── Main ─────────────────────────────────────────────────
async def main():
    log.info("Starting AKILE Stock Monitor (polling mode)")

    # Auto-subscribe admin
    initial_kw = cfg["monitor"].get("keywords", [])
    if initial_kw:
        db.upsert_user(ADMIN_CHAT_ID, first_name="Admin")
        db.set_admin(ADMIN_CHAT_ID, True)
        for kw in initial_kw:
            db.add_subscription(ADMIN_CHAT_ID, kw)
        log.info("Admin auto-subscribed to: %s", initial_kw)

    if BARK_URL:
        db.upsert_user(ADMIN_CHAT_ID)
        db.set_bark_url(ADMIN_CHAT_ID, BARK_URL)
        log.info("Admin Bark URL synced from config")

    # Start bot command handler in background thread
    if BOT_TOKEN:
        def _run_bot():
            import asyncio as _aio
            _loop = _aio.new_event_loop()
            _aio.set_event_loop(_loop)
            _loop.run_until_complete(bot_poll_loop(BOT_TOKEN, ADMIN_CHAT_ID))
        bot_thread = threading.Thread(target=_run_bot, daemon=True)
        bot_thread.start()
        log.info("Bot command handler started in background")

    # Connect Telethon
    await client.connect()
    me = await client.get_me()
    log.info("Logged in as: %s (id=%s)", me.first_name, me.id)
    log.info("Monitoring channel: @%s", CHANNEL)
    log.info("Bot token: %s", "configured" if BOT_TOKEN else "NOT SET")
    log.info("Admin chat_id: %s", ADMIN_CHAT_ID)
    log.info("Waiting for restock messages...")

    await asyncio.gather(
        poll_channel(),
        health_check_loop(),
    )


if __name__ == "__main__":
    client.loop.run_until_complete(main())
