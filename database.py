import sqlite3
import logging

DB_PATH = "konkurs.db"
logger = logging.getLogger(__name__)


def init_db():
    """Bazani ishga tushirish va jadvallarni yaratish."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS channels (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id    INTEGER UNIQUE NOT NULL,
            channel_username TEXT,
            channel_title TEXT,
            invite_link   TEXT,
            added_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER UNIQUE NOT NULL,
            username   TEXT,
            full_name  TEXT,
            joined_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()
    logger.info("Ma'lumotlar bazasi tayyor.")


# ── Channels ──────────────────────────────────────────────────────────────────

def add_channel(channel_id: int, channel_username: str,
                channel_title: str, invite_link: str = None) -> bool:
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("""
            INSERT OR REPLACE INTO channels
                (channel_id, channel_username, channel_title, invite_link)
            VALUES (?, ?, ?, ?)
        """, (channel_id, channel_username, channel_title, invite_link))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Kanal qo'shishda xatolik: {e}")
        return False
    finally:
        conn.close()


def get_channels() -> list:
    """(channel_id, channel_username, channel_title, invite_link) ro'yxati."""
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.execute("""
            SELECT channel_id, channel_username, channel_title, invite_link
            FROM channels
        """)
        return cur.fetchall()
    finally:
        conn.close()


def channel_exists(channel_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.execute(
            "SELECT 1 FROM channels WHERE channel_id = ?", (channel_id,)
        )
        return cur.fetchone() is not None
    finally:
        conn.close()


def remove_channel(channel_id: int):
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("DELETE FROM channels WHERE channel_id = ?", (channel_id,))
        conn.commit()
    finally:
        conn.close()


def get_channel_count() -> int:
    conn = sqlite3.connect(DB_PATH)
    try:
        return conn.execute("SELECT COUNT(*) FROM channels").fetchone()[0]
    finally:
        conn.close()


# ── Users ─────────────────────────────────────────────────────────────────────

def add_user(user_id: int, username: str, full_name: str):
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("""
            INSERT OR IGNORE INTO users (user_id, username, full_name)
            VALUES (?, ?, ?)
        """, (user_id, username, full_name))
        conn.commit()
    except Exception as e:
        logger.error(f"Foydalanuvchi qo'shishda xatolik: {e}")
    finally:
        conn.close()


def get_user_count() -> int:
    conn = sqlite3.connect(DB_PATH)
    try:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    finally:
        conn.close()


def get_all_user_ids() -> list:
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.execute("SELECT user_id FROM users")
        return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()
