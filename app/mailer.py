import os
import smtplib
import threading
from email.message import EmailMessage

import httpx


def _send_resend(to, subject, body):
    r = httpx.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {os.getenv('RESEND_API_KEY')}"},
        json={"from": os.getenv("MAIL_FROM", "Mendly <onboarding@resend.dev>"),
              "to": [to], "subject": subject, "text": body},
        timeout=20,
    )
    print("[mail] resend status", r.status_code)
    return r.status_code < 300


def _send_smtp(to, subject, body):
    user, pwd = os.getenv("SMTP_USER"), os.getenv("SMTP_PASS")
    msg = EmailMessage()
    msg["From"] = f"Mendly <{user}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(os.getenv("SMTP_HOST", "smtp.gmail.com"),
                      int(os.getenv("SMTP_PORT", "587")), timeout=20) as s:
        s.starttls()
        s.login(user, pwd)
        s.send_message(msg)
    return True


def send_email(to, subject, body):
    if not to:
        print(f"[mail] skipped, no recipient: {subject}")
        return False
    try:
        if os.getenv("RESEND_API_KEY"):
            return _send_resend(to, subject, body)
        if os.getenv("SMTP_USER") and os.getenv("SMTP_PASS"):
            return _send_smtp(to, subject, body)
        print(f"[mail] skipped, not configured: {subject}")
    except Exception as e:
        print("[mail] failed:", str(e)[:150])
    return False


def send_async(to, subject, body):
    threading.Thread(target=send_email, args=(to, subject, body), daemon=True).start()


def notify_manager(issue_id, status, reason):
    base = os.getenv("BASE_URL", "http://127.0.0.1:8000")
    send_async(
        os.getenv("MANAGER_EMAIL"),
        f"Mendly: job #{issue_id} needs your attention ({status})",
        f"Job #{issue_id} is now: {status}.\n{reason}\n\n"
        f"Open it (sign in first):\n{base}/manager/issue/{issue_id}\n\n- Mendly",
    )