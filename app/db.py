import os
import sqlite3
from datetime import datetime

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mendly.db"
)

# Status names: use these everywhere, never type the strings by hand
S_NEW = "New"
S_ANALYZED = "Analyzed"
S_QUOTES_REQUESTED = "Quotes requested"
S_QUOTES_RECEIVED = "Quotes received"
S_NEEDS_MANAGER = "Needs manager"
S_SCHEDULED = "Scheduled"
S_WORK_SUBMITTED = "Work submitted"
S_VERIFIED = "Verified"
S_DISPUTED = "Disputed"
S_READY_TO_PAY = "Ready to pay"
S_PAID = "Paid"
S_PAYMENT_FAILED = "Payment failed"
S_REJECTED = "Rejected"

SCHEMA = """
CREATE TABLE IF NOT EXISTS properties (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE, address TEXT, manager_name TEXT
);
CREATE TABLE IF NOT EXISTS vendors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT, trade TEXT, email TEXT, paypal_email TEXT,
    rating REAL, is_simulated INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    property_id INTEGER, tenant_name TEXT, message TEXT, photo_path TEXT,
    repair_type TEXT, urgency TEXT, est_low REAL, est_high REAL, ai_summary TEXT,
    status TEXT, selected_vendor_id INTEGER, after_photo_path TEXT,
    tenant_confirmed INTEGER, verify_confidence REAL, verify_reason TEXT,
    created_at TEXT, closed_at TEXT
);
CREATE TABLE IF NOT EXISTS quotes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_id INTEGER, vendor_id INTEGER, token TEXT UNIQUE,
    price REAL, earliest_date TEXT, notes TEXT,
    flag INTEGER DEFAULT 0, flag_reason TEXT,
    status TEXT DEFAULT 'invited', created_at TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_id INTEGER, actor TEXT, action TEXT, reason TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_id INTEGER, vendor_id INTEGER, amount REAL,
    paypal_order_id TEXT, paypal_capture_id TEXT, paypal_status TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    auto_approve_limit REAL, max_above_avg_pct REAL, repeat_issue_threshold INTEGER
);
CREATE TABLE IF NOT EXISTS price_history (
    repair_type TEXT PRIMARY KEY, avg_price REAL
);
"""


def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def now():
    return datetime.now().isoformat(timespec="seconds")


def init_db():
    conn = get_conn()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def get_issue(issue_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM issues WHERE id = ?", (issue_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def add_event(issue_id, actor, action, reason=""):
    conn = get_conn()
    conn.execute(
        "INSERT INTO events (issue_id, actor, action, reason, created_at) VALUES (?,?,?,?,?)",
        (issue_id, actor, action, reason, now()),
    )
    conn.commit()
    conn.close()


def set_status(issue_id, status, actor="system", reason=""):
    conn = get_conn()
    conn.execute("UPDATE issues SET status = ? WHERE id = ?", (status, issue_id))
    conn.commit()
    conn.close()
    add_event(issue_id, actor, f"Status: {status}", reason)


def get_settings():
    conn = get_conn()
    row = conn.execute("SELECT * FROM settings WHERE id = 1").fetchone()
    conn.close()
    return dict(row)


def get_avg_price(repair_type):
    conn = get_conn()
    row = conn.execute(
        "SELECT avg_price FROM price_history WHERE repair_type = ?", (repair_type,)
    ).fetchone()
    conn.close()
    return row["avg_price"] if row else None