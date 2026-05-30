#!/usr/bin/env python3
"""SQLite database layer for user subscriptions."""

import sqlite3
import threading
from pathlib import Path
from typing import List, Tuple, Optional

DB_PATH = Path(__file__).parent / "data" / "subscriptions.db"


class Database:
    def __init__(self):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn"):
            self._local.conn = sqlite3.connect(
                str(DB_PATH), timeout=30
            )
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
        return self._local.conn

    def _init_db(self):
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                chat_id   INTEGER PRIMARY KEY,
                username  TEXT,
                first_name TEXT,
                bark_url  TEXT DEFAULT '',
                joined_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                is_admin  INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS subscriptions (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id   INTEGER NOT NULL,
                keyword   TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(chat_id, keyword),
                FOREIGN KEY (chat_id) REFERENCES users(chat_id)
            );
            CREATE INDEX IF NOT EXISTS idx_sub_keyword ON subscriptions(keyword);
        """)
        # Migrate: add bark_url column if missing
        try:
            conn.execute("ALTER TABLE users ADD COLUMN bark_url TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass  # column already exists
        conn.commit()

    # ── User operations ──────────────────────────────────
    def upsert_user(self, chat_id: int, username: str = "", first_name: str = ""):
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO users (chat_id, username, first_name)
               VALUES (?, ?, ?)
               ON CONFLICT(chat_id) DO UPDATE SET
                 username = excluded.username,
                 first_name = excluded.first_name""",
            (chat_id, username, first_name),
        )
        conn.commit()

    def set_admin(self, chat_id: int, is_admin: bool = True):
        conn = self._get_conn()
        conn.execute(
            "UPDATE users SET is_admin = ? WHERE chat_id = ?",
            (1 if is_admin else 0, chat_id),
        )
        conn.commit()

    def set_bark_url(self, chat_id: int, bark_url: str):
        conn = self._get_conn()
        conn.execute(
            "UPDATE users SET bark_url = ? WHERE chat_id = ?",
            (bark_url, chat_id),
        )
        conn.commit()

    def get_bark_url(self, chat_id: int) -> str:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT bark_url FROM users WHERE chat_id = ?", (chat_id,)
        ).fetchone()
        return row["bark_url"] if row and row["bark_url"] else ""

    def get_all_bark_urls(self) -> dict:
        """Returns {chat_id: bark_url} for users who have one."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT chat_id, bark_url FROM users WHERE bark_url != ''"
        ).fetchall()
        return {r["chat_id"]: r["bark_url"] for r in rows}

    def is_admin(self, chat_id: int) -> bool:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT is_admin FROM users WHERE chat_id = ?", (chat_id,)
        ).fetchone()
        return bool(row and row["is_admin"])

    def get_user_count(self) -> int:
        conn = self._get_conn()
        row = conn.execute("SELECT COUNT(*) as cnt FROM users").fetchone()
        return row["cnt"]

    # ── Subscription operations ──────────────────────────
    MAX_SUBS_PER_USER = 20
    MIN_KEYWORD_LEN = 2

    def add_subscription(self, chat_id: int, keyword: str) -> Tuple[bool, str]:
        """Returns (success, message)."""
        keyword = keyword.strip()
        if not keyword:
            return False, "關鍵字不能為空"
        if len(keyword) < self.MIN_KEYWORD_LEN:
            return False, f"關鍵字太短（最少 {self.MIN_KEYWORD_LEN} 字符）"
        if len(keyword) > 50:
            return False, "關鍵字太長（最多 50 字符）"

        conn = self._get_conn()
        count = conn.execute(
            "SELECT COUNT(*) as cnt FROM subscriptions WHERE chat_id = ?",
            (chat_id,),
        ).fetchone()["cnt"]

        if count >= self.MAX_SUBS_PER_USER:
            return False, f"訂閱已達上限（{self.MAX_SUBS_PER_USER} 個）"

        try:
            conn.execute(
                "INSERT INTO subscriptions (chat_id, keyword) VALUES (?, ?)",
                (chat_id, keyword),
            )
            conn.commit()
            return True, f"✅ 已訂閱「{keyword}」"
        except sqlite3.IntegrityError:
            return False, f"你已經訂閱過「{keyword}」了"

    def remove_subscription(self, chat_id: int, keyword: str) -> Tuple[bool, str]:
        keyword = keyword.strip()
        conn = self._get_conn()
        cursor = conn.execute(
            "DELETE FROM subscriptions WHERE chat_id = ? AND keyword = ?",
            (chat_id, keyword),
        )
        conn.commit()
        if cursor.rowcount > 0:
            return True, f"❌ 已取消訂閱「{keyword}」"
        return False, f"你沒有訂閱「{keyword}」"

    def remove_all_subscriptions(self, chat_id: int) -> int:
        conn = self._get_conn()
        cursor = conn.execute(
            "DELETE FROM subscriptions WHERE chat_id = ?", (chat_id,)
        )
        conn.commit()
        return cursor.rowcount

    def get_user_subscriptions(self, chat_id: int) -> List[str]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT keyword FROM subscriptions WHERE chat_id = ? ORDER BY keyword",
            (chat_id,),
        ).fetchall()
        return [r["keyword"] for r in rows]

    def get_all_subscribers(self, keyword: str) -> List[int]:
        """Get all chat_ids subscribed to a keyword (case-insensitive)."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT chat_id FROM subscriptions WHERE LOWER(keyword) = LOWER(?)",
            (keyword,),
        ).fetchall()
        return [r["chat_id"] for r in rows]

    def get_all_subscriptions_map(self) -> dict:
        """Returns {keyword: [chat_id, ...]} for all subscriptions."""
        conn = self._get_conn()
        rows = conn.execute("SELECT keyword, chat_id FROM subscriptions").fetchall()
        result = {}
        for r in rows:
            kw = r["keyword"].lower()
            result.setdefault(kw, []).append(r["chat_id"])
        return result

    def get_subscription_count(self) -> int:
        conn = self._get_conn()
        row = conn.execute("SELECT COUNT(*) as cnt FROM subscriptions").fetchone()
        return row["cnt"]


# Singleton
db = Database()
