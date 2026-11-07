import os
import secrets
import threading
import time
from datetime import datetime, timedelta

from app import ai, db

UPLOAD_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "static", "uploads"
)


def start(issue_id):
    issue = db.get_issue(issue_id)
    photo_fs = os.path.join(UPLOAD_DIR, issue["photo_path"])

    result, used_ai = ai.analyze_issue(photo_fs, issue["message"])

    conn = db.get_conn()
    conn.execute(
        """UPDATE issues SET repair_type=?, urgency=?, est_low=?, est_high=?, ai_summary=?
           WHERE id=?""",
        (result["repair_type"], result["urgency"], result["est_low"],
         result["est_high"], result["summary"], issue_id),
    )
    conn.commit()
    conn.close()

    source = "AI analyzed photo" if used_ai else "Keyword fallback used (AI unavailable)"
    db.add_event(
        issue_id, "ai", source,
        f"{result['repair_type']}, {result['urgency']} urgency, "
        f"${result['est_low']:.0f}-${result['est_high']:.0f}",
    )
    db.set_status(issue_id, db.S_ANALYZED, actor="agent", reason="Analysis saved")
    invite_vendors(issue_id)
def invite_vendors(issue_id, max_vendors=3):
    issue = db.get_issue(issue_id)
    conn = db.get_conn()
    vendors = conn.execute(
        """SELECT * FROM vendors WHERE trade = ?
           ORDER BY is_simulated ASC, rating DESC LIMIT ?""",
        (issue["repair_type"], max_vendors),
    ).fetchall()
    if not vendors:
        conn.close()
        db.set_status(issue_id, db.S_NEEDS_MANAGER, actor="agent",
                      reason=f"No approved {issue['repair_type']} vendors")
        return
    for v in vendors:
        conn.execute(
            """INSERT INTO quotes (issue_id, vendor_id, token, status, created_at)
               VALUES (?,?,?,?,?)""",
            (issue_id, v["id"], secrets.token_urlsafe(16), "invited", db.now()),
        )
    conn.commit()
    conn.close()

    names = ", ".join(v["name"] for v in vendors)
    db.add_event(issue_id, "agent", f"{len(vendors)} vendors invited for quotes", names)
    db.set_status(issue_id, db.S_QUOTES_REQUESTED, actor="agent",
                  reason="Private links created")
    threading.Thread(target=_simulate_quotes, args=(issue_id,), daemon=True).start()


def _simulate_quotes(issue_id):
    """Demo helper: simulated vendors reply after a few seconds."""
    issue = db.get_issue(issue_id)
    avg = db.get_avg_price(issue["repair_type"]) or 120
    conn = db.get_conn()
    rows = conn.execute(
        """SELECT q.id, v.name FROM quotes q JOIN vendors v ON v.id = q.vendor_id
           WHERE q.issue_id = ? AND v.is_simulated = 1 AND q.status = 'invited'
           ORDER BY q.id""",
        (issue_id,),
    ).fetchall()
    conn.close()

    multipliers = [0.95, 1.40, 1.05]  # one fair, one high, one slightly above average
    for i, row in enumerate(rows):
        time.sleep(3 + i * 2)
        price = round(avg * multipliers[i % len(multipliers)])
        date = (datetime.now() + timedelta(days=1 + i)).strftime("%Y-%m-%d")
        conn = db.get_conn()
        conn.execute(
            """UPDATE quotes SET price = ?, earliest_date = ?, notes = ?, status = 'submitted'
               WHERE id = ?""",
            (price, date, "Simulated vendor reply", row["id"]),
        )
        conn.commit()
        conn.close()
        db.add_event(issue_id, row["name"], "Quote submitted", f"${price}")
        check_all_quotes_in(issue_id)


def check_all_quotes_in(issue_id):
    conn = db.get_conn()
    pending = conn.execute(
        "SELECT COUNT(*) AS c FROM quotes WHERE issue_id = ? AND status = 'invited'",
        (issue_id,),
    ).fetchone()["c"]
    conn.close()
    issue = db.get_issue(issue_id)
    if pending == 0 and issue["status"] == db.S_QUOTES_REQUESTED:
        db.set_status(issue_id, db.S_QUOTES_RECEIVED, actor="agent",
                      reason="All invited vendors responded")