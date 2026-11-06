import os
import secrets
from datetime import datetime, timedelta

from app import db


def run():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)
    db.init_db()
    conn = db.get_conn()
    c = conn.cursor()

    # Settings and average prices
    c.execute("INSERT INTO settings VALUES (1, 300, 25, 3)")
    for t, p in [("plumbing", 150), ("electrical", 110), ("hvac", 280), ("general", 120)]:
        c.execute("INSERT INTO price_history VALUES (?,?)", (t, p))

    # Properties
    props = [
        ("OAK12", "12 Oak Street", "Maria Garcia"),
        ("PINE88", "88 Pine Avenue", "Maria Garcia"),
    ]
    for p in props:
        c.execute("INSERT INTO properties (code, address, manager_name) VALUES (?,?,?)", p)

    # Vendors (rating out of 5). Only the first one is "real".
    vendors = [
        ("AquaFix Plumbing", "plumbing", "dispatch@aquafix.example", "aquafix@example.com", 4.7, 0),
        ("RooterPro", "plumbing", "jobs@rooterpro.example", "rooterpro@example.com", 4.6, 1),
        ("PipeRight Services", "plumbing", "hello@piperight.example", "piperight@example.com", 4.5, 1),
        ("BrightFix Electric", "electrical", "book@brightfix.example", "brightfix@example.com", 4.8, 1),
        ("CoolRight HVAC", "hvac", "service@coolright.example", "coolright@example.com", 4.4, 1),
        ("Handy Hands Maintenance", "general", "team@handyhands.example", "handyhands@example.com", 4.3, 1),
    ]
    for v in vendors:
        c.execute(
            "INSERT INTO vendors (name, trade, email, paypal_email, rating, is_simulated) VALUES (?,?,?,?,?,?)",
            v,
        )

    # Past completed issues: (property_id, message, type, vendor_id, price, flagged_price, days_ago)
    past = [
        (1, "Bathroom tap dripping", "plumbing", 2, 140, 195, 25),
        (1, "Toilet not flushing", "plumbing", 3, 160, None, 22),
        (2, "Light fixture flickering", "electrical", 4, 95, None, 20),
        (2, "AC not cooling", "hvac", 5, 310, 420, 17),
        (1, "Window latch broken", "general", 6, 110, None, 14),
        (2, "Kitchen sink clogged", "plumbing", 1, 145, None, 10),
        (1, "Outlet not working", "electrical", 4, 120, 160, 6),
        (2, "Door lock jammed", "general", 6, 130, None, 3),
    ]
    for prop_id, msg, rtype, vid, price, flagged, days in past:
        created = (datetime.now() - timedelta(days=days + 2)).isoformat(timespec="seconds")
        closed = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
        c.execute(
            """INSERT INTO issues (property_id, tenant_name, message, repair_type, urgency,
               est_low, est_high, ai_summary, status, selected_vendor_id, tenant_confirmed,
               verify_confidence, created_at, closed_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (prop_id, "Past tenant", msg, rtype, "medium", price * 0.7, price * 1.5,
             msg, db.S_PAID, vid, 1, 0.9, created, closed),
        )
        issue_id = c.lastrowid
        c.execute(
            "INSERT INTO quotes (issue_id, vendor_id, token, price, status, created_at) VALUES (?,?,?,?,?,?)",
            (issue_id, vid, secrets.token_urlsafe(12), price, "accepted", created),
        )
        if flagged:
            c.execute(
                "INSERT INTO quotes (issue_id, vendor_id, token, price, flag, flag_reason, status, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (issue_id, vid, secrets.token_urlsafe(12), flagged, 1, "Above average", "rejected", created),
            )
        c.execute(
            "INSERT INTO payments (issue_id, vendor_id, amount, paypal_status, created_at) VALUES (?,?,?,?,?)",
            (issue_id, vid, price, "COMPLETED", closed),
        )
        c.execute(
            "INSERT INTO events (issue_id, actor, action, reason, created_at) VALUES (?,?,?,?,?)",
            (issue_id, "system", "Seeded past job", "Demo history", created),
        )

    conn.commit()
    conn.close()
    print("Seed complete.")


if __name__ == "__main__":
    run()