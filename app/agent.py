import os

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
    # Next steps (vendor selection and quotes) are added in a later step.