import os
import sqlite3
import uuid
from datetime import datetime, timezone

DATABASE_URL = os.getenv("DATABASE_URL", "")
# This compact starter uses SQLite locally. For production, configure PostgreSQL and replace this
# adapter with psycopg/SQLAlchemy before launch; see README. Railway ephemeral disks are not durable.
DB_PATH = os.getenv("SQLITE_PATH", "bot.db")


def _connect():
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _connect() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS orders (
            order_id TEXT PRIMARY KEY,
            telegram_user_id INTEGER NOT NULL,
            mobile TEXT NOT NULL,
            status TEXT NOT NULL,
            provider_txn_id TEXT UNIQUE,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS screenshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT NOT NULL,
            telegram_user_id INTEGER NOT NULL,
            telegram_file_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(order_id) REFERENCES orders(order_id)
        )""")


def now():
    return datetime.now(timezone.utc).isoformat()


def create_order(telegram_user_id, mobile):
    order_id = uuid.uuid4().hex[:12].upper()
    timestamp = now()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO orders(order_id, telegram_user_id, mobile, status, created_at, updated_at) VALUES(?,?,?,?,?,?)",
            (order_id, telegram_user_id, mobile, "CREATED", timestamp, timestamp),
        )
    return order_id


def get_order(order_id):
    with _connect() as conn:
        row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
        return dict(row) if row else None


def list_orders(limit=20):
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM orders ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]


def update_order_status(order_id, status, provider_txn_id=None):
    allowed = {
        "CREATED", "AWAITING_PAYMENT", "PAYMENT_PENDING", "PAYMENT_VERIFIED",
        "PAYMENT_FAILED", "ACTIVATION_PENDING", "ACTIVATION_CONFIRMED",
        "ACTIVATION_FAILED", "CANCELLED"
    }
    if status not in allowed:
        raise ValueError("Invalid order status")
    with _connect() as conn:
        if provider_txn_id:
            conn.execute(
                "UPDATE orders SET status=?, provider_txn_id=?, updated_at=? WHERE order_id=?",
                (status, provider_txn_id, now(), order_id),
            )
        else:
            conn.execute(
                "UPDATE orders SET status=?, updated_at=? WHERE order_id=?",
                (status, now(), order_id),
            )


def save_screenshot(order_id, telegram_user_id, telegram_file_id):
    with _connect() as conn:
        conn.execute(
            "INSERT INTO screenshots(order_id, telegram_user_id, telegram_file_id, created_at) VALUES(?,?,?,?)",
            (order_id, telegram_user_id, telegram_file_id, now()),
        )
