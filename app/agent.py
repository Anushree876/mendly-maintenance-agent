import os
import secrets
import threading
import time
from datetime import datetime, timedelta

from app import ai, db, mailer

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
    invites = []
    for v in vendors:
        token = secrets.token_urlsafe(16)
        conn.execute(
            """INSERT INTO quotes (issue_id, vendor_id, token, status, created_at)
               VALUES (?,?,?,?,?)""",
            (issue_id, v["id"], token, "invited", db.now()),
        )
        invites.append((dict(v), token))
    conn.commit()
    conn.close()
    base = os.getenv("BASE_URL", "http://127.0.0.1:8000")
    for v, token in invites:
        if not v["is_simulated"]:
            mailer.send_async(
                os.getenv("REAL_VENDOR_EMAIL") or v["email"],
                f"New {issue['repair_type']} job to quote",
                f"Hi {v['name']},\n\nA tenant reported: {issue['message']}\n"
                f"AI summary: {issue['ai_summary']}\n\n"
                f"Send your quote here (private link):\n{base}/v/{token}\n\n- Mendly",
            )

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

_lock = threading.Lock()


def check_all_quotes_in(issue_id):
    with _lock:
        conn = db.get_conn()
        pending = conn.execute(
            "SELECT COUNT(*) AS c FROM quotes WHERE issue_id = ? AND status = 'invited'",
            (issue_id,),
        ).fetchone()["c"]
        conn.close()
        issue = db.get_issue(issue_id)
        if not (pending == 0 and issue["status"] == db.S_QUOTES_REQUESTED):
            return
        db.set_status(issue_id, db.S_QUOTES_RECEIVED, actor="agent",
                      reason="All invited vendors responded")
    evaluate_quotes(issue_id)


def evaluate_quotes(issue_id):
    issue = db.get_issue(issue_id)
    settings = db.get_settings()
    limit = settings["auto_approve_limit"]
    max_pct = settings["max_above_avg_pct"]

    conn = db.get_conn()
    rows = conn.execute(
        """SELECT q.*, v.name AS vendor_name, v.rating AS rating FROM quotes q
           JOIN vendors v ON v.id = q.vendor_id
           WHERE q.issue_id = ? AND q.status = 'submitted' ORDER BY q.id""",
        (issue_id,),
    ).fetchall()
    quotes = [dict(r) for r in rows]
    if not quotes:
        conn.close()
        db.set_status(issue_id, db.S_NEEDS_MANAGER, actor="agent", reason="No quotes received")
        return

    avg = db.get_avg_price(issue["repair_type"]) or (sum(q["price"] for q in quotes) / len(quotes))

    # Rule check in plain Python: flag quotes too far above the usual price
    candidates = []
    flagged_events = []
    for q in quotes:
        pct = (q["price"] / avg - 1) * 100
        if pct > max_pct:
            reason = f"{pct:.0f}% above the usual ${avg:.0f}"
            conn.execute("UPDATE quotes SET flag = 1, flag_reason = ? WHERE id = ?", (reason, q["id"]))
            flagged_events.append(f"{q['vendor_name']}: ${q['price']:.0f} is {reason}")
        else:
            candidates.append(q)
    conn.commit()
    conn.close()
    for text in flagged_events:
        db.add_event(issue_id, "agent", "Quote flagged", text)

    if not candidates:
        db.set_status(issue_id, db.S_NEEDS_MANAGER, actor="agent",
                      reason="All quotes are above the price rule")
        return

    best_id, why, used_ai = ai.compare_quotes(issue, candidates, avg)
    best = next(q for q in candidates if q["id"] == best_id)

    conn = db.get_conn()
    conn.execute("UPDATE quotes SET status = 'recommended' WHERE id = ?", (best_id,))
    conn.commit()
    conn.close()
    db.add_event(issue_id, "ai" if used_ai else "agent",
                 f"Recommended {best['vendor_name']} (${best['price']:.0f})", why)

    if best["price"] <= limit:
        select_vendor(issue_id, best_id, "agent",
                      f"${best['price']:.0f} is under the ${limit:.0f} auto-approve limit")
    else:
        db.set_status(issue_id, db.S_NEEDS_MANAGER, actor="agent",
                      reason=f"${best['price']:.0f} is above the ${limit:.0f} limit, manager must approve")


def select_vendor(issue_id, quote_id, actor, reason):
    conn = db.get_conn()
    q = conn.execute(
        """SELECT q.*, v.name AS vendor_name, v.is_simulated AS is_sim, v.email AS vemail
           FROM quotes q JOIN vendors v ON v.id = q.vendor_id WHERE q.id = ?""",
        (quote_id,),
    ).fetchone()
    conn.execute("UPDATE quotes SET status = 'accepted' WHERE id = ?", (quote_id,))
    conn.execute(
        """UPDATE quotes SET status = 'declined'
           WHERE issue_id = ? AND id != ? AND status IN ('submitted','recommended')""",
        (issue_id, quote_id),
    )
    conn.execute(
        "UPDATE quotes SET status = 'closed' WHERE issue_id = ? AND id != ? AND status = 'invited'",
        (issue_id, quote_id),
    )
    conn.execute("UPDATE issues SET selected_vendor_id = ? WHERE id = ?", (q["vendor_id"], issue_id))
    conn.commit()
    conn.close()
    db.add_event(issue_id, actor, f"Approved {q['vendor_name']} at ${q['price']:.0f}", reason)
    db.add_event(issue_id, "agent", "Other vendors told: not selected", "Their links are now closed")
    db.set_status(issue_id, db.S_SCHEDULED, actor=actor, reason=f"{q['vendor_name']} booked")
    if not q["is_sim"]:
        base = os.getenv("BASE_URL", "http://127.0.0.1:8000")
        mailer.send_async(
            os.getenv("REAL_VENDOR_EMAIL") or q["vemail"],
            "You were selected for the job",
            f"You were selected at ${q['price']:.0f}.\n"
            f"When the work is done, upload a completion photo here:\n{base}/v/{q['token']}\n\n- Mendly",
        )


def reject_issue(issue_id, reason):
    conn = db.get_conn()
    conn.execute(
        "UPDATE quotes SET status = 'closed' WHERE issue_id = ? AND status != 'accepted'",
        (issue_id,),
    )
    conn.commit()
    conn.close()
    db.set_status(issue_id, db.S_REJECTED, actor="manager", reason=reason)

CONFIDENCE_MIN = 0.7


def after_work_submitted(issue_id):
    """Runs after the tenant answers the 'Is it fixed?' question."""
    issue = db.get_issue(issue_id)
    if not issue["tenant_confirmed"]:
        db.set_status(issue_id, db.S_DISPUTED, actor="tenant",
                      reason="Tenant says the problem is not fixed")
        return

    before = os.path.join(UPLOAD_DIR, issue["photo_path"])
    after = os.path.join(UPLOAD_DIR, issue["after_photo_path"])
    result, used_ai = ai.verify_fix(before, after, issue["ai_summary"])

    conn = db.get_conn()
    conn.execute(
        "UPDATE issues SET verify_confidence = ?, verify_reason = ? WHERE id = ?",
        (result["confidence"], result["reason"], issue_id),
    )
    conn.commit()
    conn.close()
    db.add_event(
        issue_id, "ai" if used_ai else "agent",
        f"Photo check: {'fixed' if result['fixed'] else 'not clearly fixed'} "
        f"({result['confidence'] * 100:.0f}% confidence)",
        result["reason"],
    )

    if result["fixed"] and result["confidence"] >= CONFIDENCE_MIN:
        mark_verified(issue_id, "agent", "Tenant confirmed and the photo check passed")
    else:
        db.set_status(issue_id, db.S_DISPUTED, actor="agent",
                      reason="Low confidence or not clearly fixed, so the manager must decide")


def mark_verified(issue_id, actor, reason):
    db.set_status(issue_id, db.S_VERIFIED, actor=actor, reason=reason)
    db.set_status(issue_id, db.S_READY_TO_PAY, actor="agent",
                  reason="Waiting for manager approval to pay")


def send_back_to_vendor(issue_id):
    conn = db.get_conn()
    conn.execute(
        """UPDATE issues SET after_photo_path = NULL, tenant_confirmed = NULL,
           verify_confidence = NULL, verify_reason = NULL WHERE id = ?""",
        (issue_id,),
    )
    conn.commit()
    conn.close()
    db.set_status(issue_id, db.S_SCHEDULED, actor="manager",
                  reason="Sent back to the vendor to redo or re-upload")


def mark_paid(issue_id, order_id, capture_id):
    conn = db.get_conn()
    conn.execute(
        """UPDATE payments SET paypal_capture_id = ?, paypal_status = 'COMPLETED'
           WHERE issue_id = ? AND paypal_order_id = ?""",
        (capture_id, issue_id, order_id),
    )
    conn.execute("UPDATE issues SET closed_at = ? WHERE id = ?", (db.now(), issue_id))
    conn.commit()
    conn.close()
    db.add_event(issue_id, "paypal", "Payment captured", f"Order {order_id}, capture {capture_id}")
    db.set_status(issue_id, db.S_PAID, actor="agent", reason="PayPal payment completed")