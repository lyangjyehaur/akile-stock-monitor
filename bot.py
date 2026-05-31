#!/usr/bin/env python3
"""
Telegram Bot command handler.
Uses python-telegram-bot v20+ framework for robust command handling.
Runs in a separate thread/event loop from the main polling monitor.
"""

import logging
import time
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)
from telegram.constants import ParseMode

from db import db

log = logging.getLogger("akile-bot")

HELP_TEXT = """<b>AKILE 補貨監控 Bot</b>

訂閱你想要的伺服器型號，當 @akileStock 頻道發佈補貨消息時，第一時間通知你！

<b>如何訂閱</b>
發送 <code>/subscribe</code>（或 <code>/sub</code>）加上你要監控的關鍵字，例如：
  <code>/subscribe Pro</code> — 監控所有名稱含 "Pro" 的產品
  <code>/subscribe HKL-TW</code> — 監控 HKL-TW 系列
  <code>/subscribe NAT</code> — 監控 NAT 系列
  <code>/subscribe Starter</code> — 監控 Starter 方案

一次也可以訂閱多個，用空格分隔：
  <code>/subscribe Pro Starter NAT</code>

<b>關鍵字規則</b>
  最短 2 個字符，最長 50 個字符
  不分大小寫，消息中包含即觸發
  每人最多 {max_subs} 個訂閱
  過短的關鍵字可能匹配大量產品，建議只訂閱精準關鍵字

<b>指令列表</b>
/subscribe <code>關鍵字</code>（/sub） — 訂閱
/unsubscribe <code>關鍵字</code>（/unsub） — 取消訂閱
/unsuball — 取消所有訂閱（需二次確認）
/list — 查看我的訂閱
/me — 查看個人資料
/keywords — 查看熱門關鍵字
/bark <code>URL</code> — 設定 Bark 推送
/status — 服務狀態
/help — 顯示此說明

有問題或建議請聯繫 @DanersAka"""


# ── Pending confirmations ────────────────────────────────
_pending_unsuball: dict = {}
CONFIRM_TIMEOUT = 60


# ── Helpers ──────────────────────────────────────────────
def _register_user(update: Update):
    user = update.effective_user
    if user:
        db.upsert_user(user.id, user.username or "", user.first_name or "")


async def _reply(update: Update, text: str):
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


# ── Command handlers ────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _register_user(update)
    await _reply(update, HELP_TEXT.format(max_subs=db.MAX_SUBS_PER_USER))


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _reply(update, HELP_TEXT.format(max_subs=db.MAX_SUBS_PER_USER))


async def cmd_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _register_user(update)
    chat_id = update.effective_chat.id
    if not context.args:
        await _reply(update, "用法：<code>/subscribe 關鍵字</code>\n例如：<code>/subscribe Pro</code>")
        return
    results = []
    for kw in context.args[:5]:
        ok, msg = db.add_subscription(chat_id, kw)
        results.append(msg)
    await _reply(update, "\n".join(results))


async def cmd_unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _register_user(update)
    chat_id = update.effective_chat.id
    if not context.args:
        await _reply(update, "用法：<code>/unsubscribe 關鍵字</code>")
        return
    results = []
    for kw in context.args:
        ok, msg = db.remove_subscription(chat_id, kw)
        results.append(msg)
    await _reply(update, "\n".join(results))


async def cmd_unsuball(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import time as _time
    _register_user(update)
    chat_id = update.effective_chat.id
    now = _time.time()

    if chat_id in _pending_unsuball and _pending_unsuball[chat_id] > now:
        del _pending_unsuball[chat_id]
        count = db.remove_all_subscriptions(chat_id)
        await _reply(update, f"已取消所有訂閱（共 {count} 個）" if count else "你沒有任何訂閱")
    else:
        subs = db.get_user_subscriptions(chat_id)
        if not subs:
            await _reply(update, "你沒有任何訂閱")
            return
        _pending_unsuball[chat_id] = now + CONFIRM_TIMEOUT
        await _reply(
            update,
            f"確定要取消所有 {len(subs)} 個訂閱嗎？\n\n"
            f"60 秒內再次發送 <code>/unsuball</code> 確認。",
        )


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _register_user(update)
    chat_id = update.effective_chat.id
    subs = db.get_user_subscriptions(chat_id)
    if subs:
        lines = [f"<b>你的訂閱（{len(subs)} 個）：</b>"]
        for i, kw in enumerate(subs, 1):
            lines.append(f"  {i}. <code>{kw}</code>")
        await _reply(update, "\n".join(lines))
    else:
        await _reply(update, "你還沒有訂閱任何關鍵字\n\n用 <code>/subscribe 關鍵字</code> 開始訂閱")


async def cmd_me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _register_user(update)
    user = update.effective_user
    chat_id = update.effective_chat.id
    subs = db.get_user_subscriptions(chat_id)
    bark = db.get_bark_url(chat_id)
    lines = [
        "<b>你的資料</b>\n",
        f"  chat_id：{chat_id}",
        f"  用戶名：@{user.username or '-'}",
        f"  Bark 推送：{'已設定' if bark else '未設定'}",
        f"  訂閱數：{len(subs)} / {db.MAX_SUBS_PER_USER}",
    ]
    if subs:
        lines.append("\n<b>訂閱列表：</b>")
        for kw in subs:
            lines.append(f"  - <code>{kw}</code>")
    await _reply(update, "\n".join(lines))


async def cmd_keywords(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kw_list = db.get_top_keywords(20)
    if not kw_list:
        await _reply(update, "目前暫無人訂閱任何關鍵字")
        return
    lines = [f"<b>熱門關鍵字（{len(kw_list)} 個）：</b>\n"]
    for i, kw in enumerate(kw_list, 1):
        lines.append(f"  {i}. <code>{kw['keyword']}</code> — {kw['cnt']} 人")
    lines.append(f"\n用 <code>/subscribe 關鍵字</code> 訂閱")
    await _reply(update, "\n".join(lines))


async def cmd_bark(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _register_user(update)
    chat_id = update.effective_chat.id
    if not context.args:
        current = db.get_bark_url(chat_id)
        if current:
            await _reply(
                update,
                f"你目前已設定的 Bark 推送：\n<code>{current}</code>\n\n"
                f"發送 <code>/bark URL</code> 更改，<code>/bark off</code> 取消。",
            )
        else:
            await _reply(
                update,
                "<b>設定 Bark 推送</b>\n\n"
                "Bark 是 iPhone 推送 App，設定後補貨通知會直接彈到鎖屏。\n\n"
                "用法：<code>/bark https://你的bark地址/你的key</code>\n\n"
                "取消推送：<code>/bark off</code>",
            )
        return
    if context.args[0].lower() == "off":
        db.set_bark_url(chat_id, "")
        await _reply(update, "已取消 Bark 推送")
        return
    url = context.args[0].strip()
    if not url.startswith("http"):
        await _reply(update, "URL 格式不正確，需要以 http:// 或 https:// 開頭")
        return
    db.set_bark_url(chat_id, url)
    await _reply(update, f"Bark 推送已設定！補貨時會同時推送到你的 iPhone。\n\n取消：<code>/bark off</code>")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_count = db.get_user_count()
    sub_count = db.get_subscription_count()
    subs_map = db.get_all_subscriptions_map()
    top_kw = sorted(subs_map.items(), key=lambda x: len(x[1]), reverse=True)[:5]
    top_lines = "\n".join(
        f"  <code>{kw}</code> — {len(ids)} 人" for kw, ids in top_kw
    )
    conn = db._get_conn()
    recent = conn.execute(
        "SELECT COUNT(*) as cnt FROM subscriptions WHERE created_at > datetime('now', '-1 day')"
    ).fetchone()["cnt"]
    await _reply(
        update,
        f"<b>服務狀態</b>\n\n"
        f"用戶數：{user_count}\n"
        f"訂閱數：{sub_count}\n"
        f"監控關鍵字數：{len(subs_map)}\n"
        f"近 24h 新增訂閱：{recent}\n\n"
        f"<b>熱門關鍵字：</b>\n{top_lines if top_lines else '（暫無）'}",
    )


async def cmd_health(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not db.is_admin(chat_id):
        return
    await _reply(
        update,
        "<b>健康檢查</b>\n\n"
        "Bot API: 正常\n"
        "頻道監聽: 需要查看服務器日誌\n"
        "心跳: 每 5 分鐘自動檢查\n\n"
        "查看日誌：<code>ssh oracle2 journalctl -u akile-monitor -f</code>",
    )


async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not db.is_admin(chat_id):
        return
    if not context.args:
        await _reply(update, "用法：<code>/broadcast 消息內容</code>")
        return
    msg = " ".join(context.args)
    conn = db._get_conn()
    rows = conn.execute("SELECT chat_id FROM users").fetchall()
    sent = 0
    for r in rows:
        try:
            await context.bot.send_message(
                chat_id=r["chat_id"],
                text=f"<b>公告</b>\n\n{msg}",
                parse_mode=ParseMode.HTML,
            )
            sent += 1
        except Exception:
            pass
    await _reply(update, f"已發送給 {sent}/{len(rows)} 個用戶")


# ── Admin data commands ──────────────────────────────────
async def cmd_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not db.is_admin(chat_id):
        return
    users = db.get_users_with_subs()
    if not users:
        await _reply(update, "暫無用戶")
        return
    lines = [f"<b>用戶列表（{len(users)} 人）：</b>\n"]
    for u in users:
        name = u["first_name"] or u["username"] or str(u["chat_id"])
        bark = " [Bark]" if u["bark_url"] else ""
        lines.append(f"  {name} — {u['sub_count']} 個訂閱{bark}")
    await _reply(update, "\n".join(lines))


async def cmd_recent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not db.is_admin(chat_id):
        return
    events = db.get_recent_events(10)
    if not events:
        await _reply(update, "暫無補貨記錄")
        return
    lines = ["<b>最近補貨記錄：</b>\n"]
    for e in events:
        lines.append(f"  {e['created_at']}")
        lines.append(f"    {e['product']}")
        lines.append(f"    匹配: {e['matched_kw']} | 通知: {e['notified']} 人\n")
    await _reply(update, "\n".join(lines))


async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not db.is_admin(chat_id):
        return
    kw_list = db.get_top_keywords(10)
    events_24h = db.get_event_count(24)
    if not kw_list:
        await _reply(update, "暫無訂閱數據")
        return
    lines = ["<b>關鍵字排行：</b>\n"]
    for i, kw in enumerate(kw_list, 1):
        lines.append(f"  {i}. <code>{kw['keyword']}</code> — {kw['cnt']} 人")
    lines.append(f"\n近 24h 補貨事件：{events_24h} 次")
    await _reply(update, "\n".join(lines))


async def cmd_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not db.is_admin(chat_id):
        return
    if not context.args:
        await _reply(update, "用法：<code>/user chat_id</code>")
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        await _reply(update, "chat_id 必須是數字")
        return
    detail = db.get_user_detail(uid)
    if not detail:
        await _reply(update, f"找不到用戶 {uid}")
        return
    u = detail["user"]
    subs = detail["subscriptions"]
    name = u.get("first_name") or u.get("username") or str(uid)
    lines = [
        "<b>用戶詳情：</b>\n",
        f"  名稱：{name}",
        f"  chat_id：{uid}",
        f"  username：@{u.get('username', '-')}",
        f"  Bark：{'已設定' if u.get('bark_url') else '未設定'}",
        f"  註冊：{u.get('joined_at', '-')}",
        f"\n<b>訂閱（{len(subs)} 個）：</b>",
    ]
    for s in subs:
        lines.append(f"  - <code>{s['keyword']}</code>（{s['created_at']}）")
    await _reply(update, "\n".join(lines))


# ── Public notification function ─────────────────────────
async def send_notification(bot, chat_id: int, text: str, button_url: str = None):
    """Send a notification to a user. Called by monitor.py."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    reply_markup = None
    if button_url:
        reply_markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton(text="立即下單", url=button_url)]]
        )
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
        )
        return True
    except Exception as e:
        log.warning("Notification failed for %s: %s", chat_id, e)
        return False


# ── Bot poll loop (entry point for monitor.py) ───────────
async def bot_poll_loop(token: str, admin_chat_id: int):
    """Start the bot application with python-telegram-bot framework.
    This function runs forever in its own event loop (separate thread).
    """
    log.info("Bot poll loop started (framework)")

    app = Application.builder().token(token).build()

    # Register all command handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("subscribe", cmd_subscribe))
    app.add_handler(CommandHandler("sub", cmd_subscribe))
    app.add_handler(CommandHandler("unsubscribe", cmd_unsubscribe))
    app.add_handler(CommandHandler("unsub", cmd_unsubscribe))
    app.add_handler(CommandHandler("unsuball", cmd_unsuball))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("me", cmd_me))
    app.add_handler(CommandHandler("keywords", cmd_keywords))
    app.add_handler(CommandHandler("bark", cmd_bark))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("health", cmd_health))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))
    app.add_handler(CommandHandler("users", cmd_users))
    app.add_handler(CommandHandler("recent", cmd_recent))
    app.add_handler(CommandHandler("top", cmd_top))
    app.add_handler(CommandHandler("user", cmd_user))

    # Start polling — this blocks until the application is stopped
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    log.info("Bot framework polling started")

    # Keep running forever
    import asyncio
    while True:
        await asyncio.sleep(3600)
