import sqlite3
import logging

DB_PATH = "konkurs.db"
logger  = logging.getLogger(__name__)


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Kanallar (kanal egalari qo'shgan)
    c.execute("""
        CREATE TABLE IF NOT EXISTS channels (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id       INTEGER UNIQUE NOT NULL,
            channel_username TEXT,
            channel_title    TEXT,
            invite_link      TEXT,
            owner_id         INTEGER,
            added_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Foydalanuvchilar
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id   INTEGER UNIQUE NOT NULL,
            username  TEXT,
            fullname  TEXT,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()
    logger.info("DB tayyor.")


# ── Channels ──────────────────────────────────────────────────────────────────

def add_channel(channel_id, username, title, invite_link, owner_id) -> bool:
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("""
            INSERT OR REPLACE INTO channels
              (channel_id, channel_username, channel_title, invite_link, owner_id)
            VALUES (?,?,?,?,?)
        """, (channel_id, username, title, invite_link, owner_id))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"add_channel: {e}")
        return False
    finally:
        conn.close()


def channel_exists(channel_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    try:
        return conn.execute(
            "SELECT 1 FROM channels WHERE channel_id=?", (channel_id,)
        ).fetchone() is not None
    finally:
        conn.close()


def get_channels() -> list:
    conn = sqlite3.connect(DB_PATH)
    try:
        return conn.execute(
            "SELECT channel_id, channel_username, channel_title, invite_link FROM channels"
        ).fetchall()
    finally:
        conn.close()


def get_channel_count() -> int:
    conn = sqlite3.connect(DB_PATH)
    try:
        return conn.execute("SELECT COUNT(*) FROM channels").fetchone()[0]
    finally:
        conn.close()


def remove_channel(channel_id: int):
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("DELETE FROM channels WHERE channel_id=?", (channel_id,))
        conn.commit()
    finally:
        conn.close()


# ── Users ─────────────────────────────────────────────────────────────────────

def add_user(user_id, username, fullname):
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("""
            INSERT OR IGNORE INTO users (user_id, username, fullname)
            VALUES (?,?,?)
        """, (user_id, username, fullname))
        conn.commit()
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
        return [r[0] for r in conn.execute("SELECT user_id FROM users").fetchall()]
    finally:
        conn.close()
