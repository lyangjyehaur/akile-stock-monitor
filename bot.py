#!/usr/bin/env python3
"""
Telegram Bot command handler.
Runs as an async loop alongside the Telethon monitor.
Uses Telegram Bot API directly (no extra dependencies).
"""

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Optional

import requests

from db import db

log = logging.getLogger("akile-bot")

CONFIG_PATH = Path(__file__).parent / "config.json"

# Pending /unsuball confirmations: {chat_id: expire_timestamp}
_pending_unsuball: dict = {}
CONFIRM_TIMEOUT = 60  # seconds


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


HELP_TEXT = """<b>AKILE 補貨監控 Bot</b>

訂閱你想要的伺服器型號，當 @akileStock 頻道發佈補貨消息時，第一時間通知你！

<b>▸ 如何訂閱</b>
發送 <code>/subscribe</code> 加上你要監控的關鍵字，例如：
• <code>/subscribe Pro</code> — 監控所有名稱含 "Pro" 的產品
• <code>/subscribe HKL-TW</code> — 監控 HKL-TW 系列（如 HKL-TW-One、HKL-TW-Pro）
• <code>/subscribe NAT</code> — 監控 NAT 系列（如 TWHinet-Mini-NAT）
• <code>/subscribe Starter</code> — 監控 Starter 方案

一次也可以訂閱多個，用空格分隔：
• <code>/subscribe Pro Starter NAT</code>

<b>▸ 關鍵字規則</b>
• 最短 2 個字符，最長 50 個字符
• 不分大小寫，消息中包含即觸發
• 每人最多 {} 個訂閱
• 過短的關鍵字（如 "HK"、"SG"）可能匹配大量產品，建議只訂閱你真正需要的精準關鍵字，避免頻繁通知打擾

<b>▸ 其他指令</b>
/unsubscribe <code>關鍵字</code> — 取消指定訂閱
/unsuball — 取消所有訂閱（需二次確認）
/list — 查看我目前的訂閱列表
/bark <code>URL</code> — 設定 Bark 推送（iPhone 用戶）
/status — 查看服務運行狀態與熱門關鍵字
/help — 顯示這份說明

有問題或建議請聯繫 @DanersAka""".format(db.MAX_SUBS_PER_USER)


def send_message(token: str, chat_id: int, text: str, parse_mode: str = "HTML"):
    """Send a message via Telegram Bot API."""
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode},
            timeout=10,
        )
        return resp.status_code == 200
    except Exception as e:
        log.error("send_message error: %s", e)
        return False


def handle_update(token: str, update: dict, admin_chat_id: int):
    """Handle a single Telegram update."""
    try:
        _handle_update_inner(token, update, admin_chat_id)
    except Exception as e:
        log.error("handle_update error: %s", e)


def _handle_update_inner(token: str, update: dict, admin_chat_id: int):
    message = update.get("message")
    if not message:
        return

    chat = message.get("chat", {})
    chat_id = chat.get("id")
    text = message.get("text", "").strip()
    user = message.get("from", {})
    username = user.get("username", "")
    first_name = user.get("first_name", "")

    if not chat_id or not text:
        return

    log.info("Bot msg from %s: %s", chat_id, text)

    # Register/update user
    db.upsert_user(chat_id, username, first_name)

    # Set admin
    if chat_id == admin_chat_id and not db.is_admin(chat_id):
        db.set_admin(chat_id, True)

    # Parse command
    if not text.startswith("/"):
        return

    parts = text.split(maxsplit=1)
    cmd = parts[0].split("@")[0].lower()  # strip @botname
    args = parts[1].strip() if len(parts) > 1 else ""

    if cmd == "/start":
        send_message(token, chat_id, HELP_TEXT)

    elif cmd == "/help":
        send_message(token, chat_id, HELP_TEXT)

    elif cmd == "/subscribe":
        if not args:
            send_message(token, chat_id, "用法：<code>/subscribe 關鍵字</code>\n例如：<code>/subscribe Pro</code>")
            return
        keywords = [k.strip() for k in args.replace(",", " ").split() if k.strip()]
        results = []
        for kw in keywords[:5]:
            ok, msg = db.add_subscription(chat_id, kw)
            results.append(msg)
        send_message(token, chat_id, "\n".join(results))

    elif cmd == "/unsubscribe":
        if not args:
            send_message(token, chat_id, "用法：<code>/unsubscribe 關鍵字</code>")
            return
        keywords = [k.strip() for k in args.replace(",", " ").split() if k.strip()]
        results = []
        for kw in keywords:
            ok, msg = db.remove_subscription(chat_id, kw)
            results.append(msg)
        send_message(token, chat_id, "\n".join(results))

    elif cmd == "/unsuball":
        now = time.time()
        if chat_id in _pending_unsuball and _pending_unsuball[chat_id] > now:
            # Confirmed
            del _pending_unsuball[chat_id]
            count = db.remove_all_subscriptions(chat_id)
            send_message(token, chat_id, f"已取消所有訂閱（共 {count} 個）" if count else "你沒有任何訂閱")
        else:
            # Ask for confirmation
            subs = db.get_user_subscriptions(chat_id)
            if not subs:
                send_message(token, chat_id, "你沒有任何訂閱")
                return
            _pending_unsuball[chat_id] = now + CONFIRM_TIMEOUT
            send_message(
                token, chat_id,
                f"確定要取消所有 {len(subs)} 個訂閱嗎？\n\n"
                f"60 秒內再次發送 <code>/unsuball</code> 確認。"
            )

    elif cmd == "/list":
        subs = db.get_user_subscriptions(chat_id)
        if subs:
            lines = [f"<b>你的訂閱（{len(subs)} 個）：</b>"]
            for i, kw in enumerate(subs, 1):
                lines.append(f"  {i}. <code>{kw}</code>")
            send_message(token, chat_id, "\n".join(lines))
        else:
            send_message(token, chat_id, "你還沒有訂閱任何關鍵字\n\n用 <code>/subscribe 關鍵字</code> 開始訂閱")

    elif cmd == "/bark":
        if not args:
            current = db.get_bark_url(chat_id)
            if current:
                send_message(
                    token, chat_id,
                    f"你目前已設定的 Bark 推送：\n<code>{current}</code>\n\n"
                    f"發送 <code>/bark URL</code> 更改，<code>/bark off</code> 取消。"
                )
            else:
                send_message(
                    token, chat_id,
                    "<b>設定 Bark 推送</b>\n\n"
                    "Bark 是 iPhone 推送 App，設定後補貨通知會直接彈到鎖屏。\n\n"
                    "用法：<code>/bark https://你的bark地址/你的key</code>\n\n"
                    "範例：<code>/bark https://bark.example.com/abc123</code>\n\n"
                    "取消推送：<code>/bark off</code>"
                )
            return
        if args.lower() == "off":
            db.set_bark_url(chat_id, "")
            send_message(token, chat_id, "已取消 Bark 推送")
            return
        url = args.strip()
        if not url.startswith("http"):
            send_message(token, chat_id, "URL 格式不正確，需要以 http:// 或 https:// 開頭")
            return
        db.set_bark_url(chat_id, url)
        send_message(token, chat_id, f"Bark 推送已設定！補貨時會同時推送到你的 iPhone。\n\n取消：<code>/bark off</code>")

    elif cmd == "/status":
        user_count = db.get_user_count()
        sub_count = db.get_subscription_count()
        subs_map = db.get_all_subscriptions_map()
        top_kw = sorted(subs_map.items(), key=lambda x: len(x[1]), reverse=True)[:5]
        top_lines = "\n".join(
            f"  <code>{kw}</code> — {len(ids)} 人" for kw, ids in top_kw
        )
        # Recent activity (last 24h)
        conn = db._get_conn()
        recent = conn.execute(
            "SELECT COUNT(*) as cnt FROM subscriptions WHERE created_at > datetime('now', '-1 day')"
        ).fetchone()["cnt"]
        status = (
            f"<b>服務狀態</b>\n\n"
            f"用戶數：{user_count}\n"
            f"訂閱數：{sub_count}\n"
            f"監控關鍵字數：{len(subs_map)}\n"
            f"近 24h 新增訂閱：{recent}\n\n"
            f"<b>熱門關鍵字：</b>\n{top_lines if top_lines else '（暫無）'}"
        )
        send_message(token, chat_id, status)

    elif cmd == "/health":
        if not db.is_admin(chat_id):
            return
        try:
            resp = requests.get(
                f"https://api.telegram.org/bot{token}/getMe", timeout=5
            )
            bot_ok = resp.status_code == 200 and resp.json().get("ok")
        except Exception:
            bot_ok = False
        health = (
            f"<b>健康檢查</b>\n\n"
            f"Bot API: {'正常' if bot_ok else '異常'}\n"
            f"頻道監聽: 需要查看服務器日誌\n"
            f"心跳: 每 5 分鐘自動檢查\n\n"
            f"查看日誌：<code>ssh oracle2 journalctl -u akile-monitor -f</code>"
        )
        send_message(token, chat_id, health)

    # Admin commands
    elif cmd == "/broadcast" and db.is_admin(chat_id):
        if not args:
            send_message(token, chat_id, "用法：<code>/broadcast 消息內容</code>")
            return
        conn = db._get_conn()
        rows = conn.execute("SELECT chat_id FROM users").fetchall()
        sent = 0
        for r in rows:
            if send_message(token, r["chat_id"], f"<b>公告</b>\n\n{args}"):
                sent += 1
            time.sleep(0.05)  # rate limit
        send_message(token, chat_id, f"已發送給 {sent}/{len(rows)} 個用戶")


async def bot_poll_loop(token: str, admin_chat_id: int):
    """Async long polling loop for bot commands."""
    log.info("Bot poll loop started (async)")
    offset = 0
    while True:
        try:
            # Use asyncio.to_thread to avoid blocking the event loop
            resp = await asyncio.to_thread(
                lambda: requests.get(
                    f"https://api.telegram.org/bot{token}/getUpdates",
                    params={"offset": offset, "timeout": 20, "allowed_updates": ["message"]},
                    timeout=25,
                )
            )
            if resp.status_code != 200:
                log.warning("getUpdates failed: %d", resp.status_code)
                await asyncio.sleep(5)
                continue

            data = resp.json()
            if not data.get("ok"):
                log.warning("getUpdates not ok: %s", data)
                await asyncio.sleep(5)
                continue

            for update in data.get("result", []):
                offset = update["update_id"] + 1
                handle_update(token, update, admin_chat_id)

        except Exception as e:
            log.error("Bot poll error: %s", e)
            await asyncio.sleep(5)
