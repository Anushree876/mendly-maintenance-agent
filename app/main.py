import hashlib
import hmac
import os
import shutil
import uuid
from datetime import datetime

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image

from app import agent, db, paypal, seed

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(title="Mendly")
os.makedirs(agent.UPLOAD_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

def _asset_v():
    try:
        return int(os.path.getmtime(os.path.join(BASE_DIR, "static", "theme.css")))
    except OSError:
        return 0


templates.env.globals["asset_v"] = _asset_v

@app.on_event("startup")
def startup():
    db.init_db()


def save_photo(upload: UploadFile):
    name = f"{uuid.uuid4().hex}.jpg"
    img = Image.open(upload.file).convert("RGB")
    img.thumbnail((1280, 1280))
    img.save(os.path.join(agent.UPLOAD_DIR, name), format="JPEG", quality=85)
    return name


@app.get("/")
def home(request: Request):
    return templates.TemplateResponse(request, "landing.html", {})


@app.get("/report/{code}")
def report_form(request: Request, code: str):
    conn = db.get_conn()
    prop = conn.execute("SELECT * FROM properties WHERE code = ?", (code,)).fetchone()
    conn.close()
    if not prop:
        raise HTTPException(404, "Property not found")
    return templates.TemplateResponse(request, "tenant_new.html", {"property": dict(prop)})


@app.post("/report/{code}")
def report_submit(
    code: str,
    photo: UploadFile = File(None),
    message: str = Form(...),
    tenant_name: str = Form("Tenant"),
    use_sample: str = Form(""),
):
    conn = db.get_conn()
    prop = conn.execute("SELECT * FROM properties WHERE code = ?", (code,)).fetchone()
    if not prop:
        conn.close()
        raise HTTPException(404, "Property not found")

    try:
        photo_name = copy_sample("before") if (use_sample == "1" and demo_on()) else save_photo(photo)
    except Exception:
        conn.close()
        raise HTTPException(400, "Could not read that image. Please upload a JPG or PNG.")

    cur = conn.execute(
        """INSERT INTO issues (property_id, tenant_name, message, photo_path, status, created_at)
           VALUES (?,?,?,?,?,?)""",
        (prop["id"], tenant_name, message, photo_name, db.S_NEW, db.now()),
    )
    issue_id = cur.lastrowid
    conn.commit()
    conn.close()

    db.add_event(issue_id, "tenant", "Issue reported", message[:200])
    agent.start(issue_id)
    return RedirectResponse(f"/status/{issue_id}?new=1", status_code=303)


@app.get("/status/{issue_id}")
def status_page(request: Request, issue_id: int):
    issue = db.get_issue(issue_id)
    if not issue:
        raise HTTPException(404, "Issue not found")
    conn = db.get_conn()
    prop = conn.execute("SELECT * FROM properties WHERE id = ?", (issue["property_id"],)).fetchone()
    events = [dict(r) for r in conn.execute(
        "SELECT * FROM events WHERE issue_id = ? ORDER BY id", (issue_id,)).fetchall()]
    quotes = [dict(r) for r in conn.execute(
        """SELECT q.*, v.name AS vendor_name, v.is_simulated FROM quotes q
           JOIN vendors v ON v.id = q.vendor_id WHERE q.issue_id = ? ORDER BY q.id""",
        (issue_id,)).fetchall()]
    conn.close()
    base_url = os.getenv("BASE_URL", "http://127.0.0.1:8000")
    return templates.TemplateResponse(
        request, "tenant_status.html",
        {"issue": issue, "property": dict(prop), "events": events,
         "quotes": quotes, "base_url": base_url,
         "demo": os.getenv("DEMO_MODE", "false").lower() == "true",
         "scan": request.query_params.get("new") == "1",
         "ai_used": any(e["action"] == "AI analyzed photo" for e in events),
         "payment": payment_for(issue_id)},
    )
def get_quote_by_token(token):
    conn = db.get_conn()
    row = conn.execute(
        """SELECT q.*, v.name AS vendor_name FROM quotes q
           JOIN vendors v ON v.id = q.vendor_id WHERE q.token = ?""",
        (token,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


@app.get("/v/{token}")
def vendor_page(request: Request, token: str):
    quote = get_quote_by_token(token)
    if not quote:
        raise HTTPException(404, "This link is not valid.")
    issue = db.get_issue(quote["issue_id"])
    conn = db.get_conn()
    prop = conn.execute("SELECT * FROM properties WHERE id = ?", (issue["property_id"],)).fetchone()
    conn.close()
    return templates.TemplateResponse(
        request, "vendor_issue.html",
        {"quote": quote, "issue": issue, "property": dict(prop),
         "payment": payment_for(issue["id"])},
    )


@app.post("/v/{token}/quote")
def vendor_quote(
    token: str,
    price: float = Form(...),
    earliest_date: str = Form(...),
    notes: str = Form(""),
):
    quote = get_quote_by_token(token)
    if not quote:
        raise HTTPException(404, "This link is not valid.")
    if quote["status"] != "invited":
        return RedirectResponse(f"/v/{token}", status_code=303)
    if price <= 0 or price > 100000:
        raise HTTPException(400, "Please enter a valid price.")

    conn = db.get_conn()
    conn.execute(
        """UPDATE quotes SET price = ?, earliest_date = ?, notes = ?, status = 'submitted'
           WHERE token = ?""",
        (price, earliest_date, notes[:500], token),
    )
    conn.commit()
    conn.close()
    db.add_event(quote["issue_id"], quote["vendor_name"], "Quote submitted", f"${price:.0f}")
    agent.check_all_quotes_in(quote["issue_id"])
    return RedirectResponse(f"/v/{token}", status_code=303)

@app.get("/manager/issue/{issue_id}")
def manager_issue(request: Request, issue_id: int):
    issue = db.get_issue(issue_id)
    if not issue:
        raise HTTPException(404, "Issue not found")
    conn = db.get_conn()
    prop = conn.execute("SELECT * FROM properties WHERE id = ?", (issue["property_id"],)).fetchone()
    quotes = [dict(r) for r in conn.execute(
        """SELECT q.*, v.name AS vendor_name, v.rating AS rating FROM quotes q
           JOIN vendors v ON v.id = q.vendor_id
           WHERE q.issue_id = ? AND q.price IS NOT NULL ORDER BY q.price""",
        (issue_id,)).fetchall()]
    events = [dict(r) for r in conn.execute(
        "SELECT * FROM events WHERE issue_id = ? ORDER BY id", (issue_id,)).fetchall()]
    conn.close()
    avg = db.get_avg_price(issue["repair_type"])
    conn = db.get_conn()
    pay_row = conn.execute(
        """SELECT p.*, v.name AS vendor_name FROM payments p
           JOIN vendors v ON v.id = p.vendor_id
           WHERE p.issue_id = ? AND p.paypal_status = 'COMPLETED'
           ORDER BY p.id DESC LIMIT 1""",
        (issue_id,),
    ).fetchone()
    conn.close()
    return templates.TemplateResponse(
        request, "manager_issue.html",
        {"issue": issue, "property": dict(prop), "quotes": quotes,
         "events": events, "avg": avg, "settings": db.get_settings(),
         "payment": dict(pay_row) if pay_row else None},
    )


@app.post("/manager/issue/{issue_id}/approve")
def manager_approve(issue_id: int, quote_id: int = Form(...)):
    issue = db.get_issue(issue_id)
    if not issue or issue["status"] != db.S_NEEDS_MANAGER:
        raise HTTPException(400, "This issue is not waiting for approval.")
    conn = db.get_conn()
    q = conn.execute(
        "SELECT id FROM quotes WHERE id = ? AND issue_id = ? AND price IS NOT NULL",
        (quote_id, issue_id),
    ).fetchone()
    conn.close()
    if not q:
        raise HTTPException(400, "Quote not found for this issue.")
    agent.select_vendor(issue_id, quote_id, "manager", "Approved by the manager")
    return RedirectResponse(f"/manager/issue/{issue_id}", status_code=303)


@app.post("/manager/issue/{issue_id}/reject")
def manager_reject(issue_id: int):
    issue = db.get_issue(issue_id)
    if not issue or issue["status"] != db.S_NEEDS_MANAGER:
        raise HTTPException(400, "This issue is not waiting for approval.")
    agent.reject_issue(issue_id, "Rejected by the manager")
    return RedirectResponse(f"/manager/issue/{issue_id}", status_code=303)

@app.post("/v/{token}/done")
def vendor_done(token: str, after_photo: UploadFile = File(None), use_sample: str = Form("")):
    quote = get_quote_by_token(token)
    if not quote:
        raise HTTPException(404, "This link is not valid.")
    issue = db.get_issue(quote["issue_id"])
    if quote["status"] != "accepted" or issue["status"] != db.S_SCHEDULED:
        raise HTTPException(400, "This job is not open for a completion photo.")
    try:
        name = copy_sample("after") if (use_sample == "1" and demo_on()) else save_photo(after_photo)
    except Exception:
        raise HTTPException(400, "Could not read that image. Please upload a JPG or PNG.")

    conn = db.get_conn()
    conn.execute("UPDATE issues SET after_photo_path = ? WHERE id = ?", (name, issue["id"]))
    conn.commit()
    conn.close()
    db.add_event(issue["id"], quote["vendor_name"], "Completion photo uploaded", "")
    db.set_status(issue["id"], db.S_WORK_SUBMITTED, actor=quote["vendor_name"],
                  reason="Work marked as done")
    return RedirectResponse(f"/v/{token}", status_code=303)


@app.post("/status/{issue_id}/confirm")
def tenant_confirm(issue_id: int, answer: str = Form(...)):
    issue = db.get_issue(issue_id)
    if not issue:
        raise HTTPException(404, "Issue not found")
    if issue["status"] != db.S_WORK_SUBMITTED:
        return RedirectResponse(f"/status/{issue_id}", status_code=303)
    fixed = 1 if answer == "yes" else 0
    conn = db.get_conn()
    conn.execute("UPDATE issues SET tenant_confirmed = ? WHERE id = ?", (fixed, issue_id))
    conn.commit()
    conn.close()
    db.add_event(issue_id, "tenant", "Tenant answered", "Fixed" if fixed else "Still broken")
    agent.after_work_submitted(issue_id)
    return RedirectResponse(f"/status/{issue_id}", status_code=303)


@app.post("/manager/issue/{issue_id}/verify")
def manager_verify(issue_id: int):
    issue = db.get_issue(issue_id)
    if not issue or issue["status"] != db.S_DISPUTED:
        raise HTTPException(400, "This issue is not in dispute.")
    agent.mark_verified(issue_id, "manager", "Manager overrode the dispute")
    return RedirectResponse(f"/manager/issue/{issue_id}", status_code=303)


@app.post("/manager/issue/{issue_id}/redo")
def manager_redo(issue_id: int):
    issue = db.get_issue(issue_id)
    if not issue or issue["status"] != db.S_DISPUTED:
        raise HTTPException(400, "This issue is not in dispute.")
    agent.send_back_to_vendor(issue_id)
    return RedirectResponse(f"/manager/issue/{issue_id}", status_code=303)

@app.post("/manager/issue/{issue_id}/pay")
def manager_pay(issue_id: int):
    issue = db.get_issue(issue_id)
    if not issue or issue["status"] != db.S_READY_TO_PAY:
        raise HTTPException(400, "This issue is not ready to pay.")

    conn = db.get_conn()
    q = conn.execute(
        """SELECT q.price, q.vendor_id, v.name AS vendor_name FROM quotes q
           JOIN vendors v ON v.id = q.vendor_id
           WHERE q.issue_id = ? AND q.status = 'accepted'""",
        (issue_id,),
    ).fetchone()
    attempts = conn.execute(
        "SELECT COUNT(*) AS c FROM payments WHERE issue_id = ? AND paypal_order_id IS NOT NULL",
        (issue_id,),
    ).fetchone()["c"]
    conn.close()
    if not q:
        raise HTTPException(400, "No selected vendor for this issue.")

    base_url = os.getenv("BASE_URL", "http://127.0.0.1:8000")
    try:
        order_id, approve_url = paypal.create_order(
            amount=q["price"],
            issue_id=issue_id,
            request_id=f"mendly-issue-{issue_id}-{attempts + 1}",
            return_url=f"{base_url}/paypal/return?issue_id={issue_id}",
            cancel_url=f"{base_url}/paypal/cancel?issue_id={issue_id}",
            description=f"Mendly job #{issue_id}: {q['vendor_name']}",
        )
    except Exception as e:
        db.add_event(issue_id, "paypal", "Could not start payment", str(e)[:150])
        raise HTTPException(502, "PayPal did not accept the request. Please try again.")

    conn = db.get_conn()
    conn.execute(
        """INSERT INTO payments (issue_id, vendor_id, amount, paypal_order_id, paypal_status, created_at)
           VALUES (?,?,?,?,?,?)""",
        (issue_id, q["vendor_id"], q["price"], order_id, "CREATED", db.now()),
    )
    conn.commit()
    conn.close()
    db.add_event(issue_id, "manager", f"Approved payment of ${q['price']:.2f} to {q['vendor_name']}",
                 f"PayPal order {order_id} created")
    return RedirectResponse(approve_url, status_code=303)


@app.get("/paypal/return")
def paypal_return(issue_id: int, token: str):
    issue = db.get_issue(issue_id)
    if not issue:
        raise HTTPException(404, "Issue not found")
    if issue["status"] == db.S_PAID:
        return RedirectResponse(f"/manager/issue/{issue_id}", status_code=303)

    conn = db.get_conn()
    row = conn.execute(
        "SELECT id FROM payments WHERE issue_id = ? AND paypal_order_id = ?",
        (issue_id, token),
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(400, "This payment does not belong to the issue.")

    status_code, data = paypal.capture_order(token)
    if status_code in (200, 201) and data.get("status") == "COMPLETED":
        agent.mark_paid(issue_id, token, paypal.capture_id_from(data))
    else:
        # It may already be captured (for example, the page was refreshed)
        try:
            order = paypal.get_order(token)
        except Exception:
            order = {}
        if order.get("status") == "COMPLETED":
            agent.mark_paid(issue_id, token, paypal.capture_id_from(order))
        else:
            conn = db.get_conn()
            conn.execute(
                "UPDATE payments SET paypal_status = 'FAILED' WHERE issue_id = ? AND paypal_order_id = ?",
                (issue_id, token),
            )
            conn.commit()
            conn.close()
            db.add_event(issue_id, "paypal", "Payment was not completed", str(data)[:150])
    return RedirectResponse(f"/manager/issue/{issue_id}", status_code=303)


@app.get("/paypal/cancel")
def paypal_cancel(issue_id: int):
    db.add_event(issue_id, "manager", "Payment cancelled", "Left PayPal without paying")
    return RedirectResponse(f"/manager/issue/{issue_id}", status_code=303)



# ---------- Manager login ----------

def _auth_token():
    pw = os.getenv("MANAGER_PASSWORD", "")
    return hmac.new(pw.encode(), b"mendly-manager", hashlib.sha256).hexdigest()


def is_manager(request: Request):
    if not os.getenv("MANAGER_PASSWORD"):
        return False
    return hmac.compare_digest(request.cookies.get("mendly_auth", ""), _auth_token())


@app.middleware("http")
async def manager_guard(request: Request, call_next):
    if request.url.path.startswith("/manager") and not is_manager(request):
        return RedirectResponse("/login", status_code=303)
    return await call_next(request)


@app.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login")
def login_submit(request: Request, password: str = Form(...)):
    expected = os.getenv("MANAGER_PASSWORD", "")
    if expected and hmac.compare_digest(password.encode(), expected.encode()):
        resp = RedirectResponse("/manager", status_code=303)
        resp.set_cookie(
            "mendly_auth", _auth_token(), httponly=True, samesite="lax",
            max_age=60 * 60 * 12,
            secure=os.getenv("BASE_URL", "").startswith("https"),
        )
        return resp
    return templates.TemplateResponse(
        request, "login.html", {"error": "Wrong password."}, status_code=401
    )


@app.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie("mendly_auth")
    return resp


# ---------- Manager dashboard ----------

def dashboard_data():
    conn = db.get_conn()
    month = datetime.now().strftime("%Y-%m")
    spend = conn.execute(
        """SELECT COALESCE(SUM(amount), 0) AS s FROM payments
           WHERE paypal_status = 'COMPLETED' AND created_at LIKE ?""",
        (month + "%",),
    ).fetchone()["s"]

    rows = conn.execute(
        """SELECT
             (SELECT MAX(price) FROM quotes WHERE issue_id = i.id AND flag = 1) AS flagged_price,
             (SELECT price FROM quotes WHERE issue_id = i.id AND status = 'accepted') AS accepted_price
           FROM issues i"""
    ).fetchall()
    saved = sum(
        max(0, r["flagged_price"] - r["accepted_price"])
        for r in rows if r["flagged_price"] and r["accepted_price"]
    )

    open_count = conn.execute(
        "SELECT COUNT(*) AS c FROM issues WHERE status NOT IN (?, ?)",
        (db.S_PAID, db.S_REJECTED),
    ).fetchone()["c"]

    done = conn.execute(
        "SELECT created_at, closed_at FROM issues WHERE closed_at IS NOT NULL"
    ).fetchall()
    days = [
        (datetime.fromisoformat(r["closed_at"]) - datetime.fromisoformat(r["created_at"])).total_seconds() / 86400
        for r in done
    ]
    avg_days = sum(days) / len(days) if days else 0

    issues = [dict(r) for r in conn.execute(
        """SELECT i.id, p.address, i.message, i.repair_type, i.urgency, i.status,
                  i.created_at, v.name AS vendor,
                  (SELECT price FROM quotes WHERE issue_id = i.id AND status = 'accepted') AS price
           FROM issues i
           JOIN properties p ON p.id = i.property_id
           LEFT JOIN vendors v ON v.id = i.selected_vendor_id
           ORDER BY i.id DESC"""
    ).fetchall()]
    conn.close()
    stats = {"spend": spend, "saved": saved, "open": open_count, "avg_days": avg_days}
    return stats, issues


@app.get("/manager")
def manager_dashboard(request: Request):
    stats, issues = dashboard_data()
    return templates.TemplateResponse(
        request, "manager_dashboard.html",
        {"stats": stats, "issues": issues, "settings": db.get_settings(),
         "attention": attention_items(), "feed": recent_feed()},
    )


@app.post("/manager/rules")
def manager_rules(
    auto_approve_limit: float = Form(...),
    max_above_avg_pct: float = Form(...),
):
    if not (0 <= auto_approve_limit <= 100000) or not (0 <= max_above_avg_pct <= 500):
        raise HTTPException(400, "Rule values are out of range.")
    conn = db.get_conn()
    conn.execute(
        "UPDATE settings SET auto_approve_limit = ?, max_above_avg_pct = ? WHERE id = 1",
        (auto_approve_limit, max_above_avg_pct),
    )
    conn.commit()
    conn.close()
    return RedirectResponse("/manager/rules?saved=1", status_code=303)

# ---------- Needs attention ----------

URGENCY_RANK = {"high": 0, "medium": 1, "low": 2}
OVERDUE_AFTER_HOURS = {db.S_QUOTES_REQUESTED: 24, db.S_WORK_SUBMITTED: 48}
ACTION_LABELS = {"approval": "Review quotes", "disputed": "Decide",
                 "pay": "Approve and pay", "overdue": "Take a look"}


def human_ago(iso):
    try:
        secs = (datetime.now() - datetime.fromisoformat(iso)).total_seconds()
    except (TypeError, ValueError):
        return ""
    if secs < 3600:
        return f"{max(1, int(secs // 60))} min"
    if secs < 86400:
        h = int(secs // 3600)
        return f"{h} hour" + ("s" if h != 1 else "")
    d = int(secs // 86400)
    return f"{d} day" + ("s" if d != 1 else "")


def attention_items():
    limit = db.get_settings()["auto_approve_limit"]
    conn = db.get_conn()
    rows = conn.execute(
        """SELECT i.*, p.address,
                  (SELECT MAX(created_at) FROM events WHERE issue_id = i.id) AS last_event
           FROM issues i JOIN properties p ON p.id = i.property_id
           WHERE i.status IN (?,?,?,?,?)""",
        (db.S_NEEDS_MANAGER, db.S_DISPUTED, db.S_READY_TO_PAY,
         db.S_QUOTES_REQUESTED, db.S_WORK_SUBMITTED),
    ).fetchall()

    items = []
    for r in rows:
        i = dict(r)
        status = i["status"]
        since = i["last_event"] or i["created_at"]
        try:
            hours = (datetime.now() - datetime.fromisoformat(since)).total_seconds() / 3600
        except (TypeError, ValueError):
            hours = 0

        if status in OVERDUE_AFTER_HOURS:
            if hours < OVERDUE_AFTER_HOURS[status]:
                continue
            kind = "overdue"
            reason = ("Vendors have not replied to the quote request"
                      if status == db.S_QUOTES_REQUESTED
                      else "Work was submitted but the tenant has not answered")
        elif status == db.S_NEEDS_MANAGER:
            kind = "approval"
            q = conn.execute(
                "SELECT price FROM quotes WHERE issue_id = ? AND status = 'recommended'",
                (i["id"],)).fetchone()
            reason = (f"Best quote ${q['price']:.0f} is above your ${limit:.0f} limit"
                      if q else "No quote passed the price rules")
        elif status == db.S_DISPUTED:
            kind = "disputed"
            reason = ("Tenant says the problem is not fixed" if i["tenant_confirmed"] == 0
                      else (i["verify_reason"] or "The photo check was not confident"))
        else:
            kind = "pay"
            q = conn.execute(
                """SELECT q.price, v.name FROM quotes q JOIN vendors v ON v.id = q.vendor_id
                   WHERE q.issue_id = ? AND q.status = 'accepted'""", (i["id"],)).fetchone()
            failed = conn.execute(
                "SELECT 1 FROM payments WHERE issue_id = ? AND paypal_status = 'FAILED' LIMIT 1",
                (i["id"],)).fetchone()
            who = f"${q['price']:.0f} to {q['name']}" if q else "the vendor"
            reason = (f"The last payment attempt did not complete. Pay {who}"
                      if failed else f"Verified. Waiting for your approval to pay {who}")

        items.append({
            "id": i["id"], "address": i["address"], "message": i["message"],
            "urgency": i["urgency"], "photo_path": i["photo_path"], "kind": kind,
            "reason": reason, "waiting": human_ago(since), "hours": hours,
            "action": ACTION_LABELS[kind],
        })
    conn.close()
    items.sort(key=lambda x: (URGENCY_RANK.get(x["urgency"], 1), -x["hours"]))
    return items


def recent_feed(limit=7):
    conn = db.get_conn()
    rows = conn.execute(
        """SELECT issue_id, actor, action, reason, created_at FROM events
           WHERE action NOT LIKE 'Status:%' AND action NOT LIKE 'Seeded%'
           ORDER BY id DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    conn.close()
    return [{**dict(r), "ago": human_ago(r["created_at"])} for r in rows]


@app.get("/manager/attention")
def manager_attention(request: Request):
    items = attention_items()
    counts = {k: sum(1 for x in items if x["kind"] == k)
              for k in ("approval", "disputed", "pay", "overdue")}
    return templates.TemplateResponse(
        request, "manager_attention.html", {"items": items, "counts": counts})


templates.env.globals["attention_count"] = lambda: len(attention_items())

# ---------- Windows: embed detection, Rules page, live data ----------

templates.env.globals["is_embed"] = lambda request: (
    request.headers.get("sec-fetch-dest") == "iframe"
    or request.query_params.get("embed") == "1"
)


@app.get("/manager/rules")
def manager_rules_page(request: Request):
    return templates.TemplateResponse(
        request, "manager_rules.html",
        {"settings": db.get_settings(), "saved": request.query_params.get("saved") == "1"},
    )


@app.get("/manager/issues.json")
def manager_issues_json():
    stats, issues = dashboard_data()
    return JSONResponse(issues)

def payment_for(issue_id):
    conn = db.get_conn()
    row = conn.execute(
        """SELECT p.*, v.name AS vendor_name FROM payments p
           JOIN vendors v ON v.id = p.vendor_id
           WHERE p.issue_id = ? AND p.paypal_status = 'COMPLETED'
           ORDER BY p.id DESC LIMIT 1""",
        (issue_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None

# ---------- Demo mode helpers ----------

def demo_on():
    return os.getenv("DEMO_MODE", "false").lower() == "true"


templates.env.globals["demo_on"] = demo_on
templates.env.globals["demo_paypal"] = lambda: (
    os.getenv("DEMO_PAYPAL_EMAIL", ""), os.getenv("DEMO_PAYPAL_PASSWORD", ""))

SAMPLE_DIR = os.path.join(BASE_DIR, "static", "samples")


def copy_sample(kind):
    name = f"{uuid.uuid4().hex}.jpg"
    shutil.copyfile(os.path.join(SAMPLE_DIR, f"{kind}.jpg"),
                    os.path.join(agent.UPLOAD_DIR, name))
    return name


@app.get("/demo/manager")
def demo_manager():
    if not demo_on():
        raise HTTPException(404, "Not found")
    resp = RedirectResponse("/manager", status_code=303)
    resp.set_cookie(
        "mendly_auth", _auth_token(), httponly=True, samesite="lax",
        max_age=60 * 60 * 12, secure=os.getenv("BASE_URL", "").startswith("https"),
    )
    return resp


@app.get("/demo/vendor")
def demo_vendor():
    if not demo_on():
        raise HTTPException(404, "Not found")
    conn = db.get_conn()
    issue = conn.execute(
        """SELECT id FROM issues WHERE tenant_name != 'Past tenant'
           AND id IN (SELECT DISTINCT issue_id FROM quotes) ORDER BY id DESC LIMIT 1"""
    ).fetchone()
    token = None
    if issue:
        rows = conn.execute(
            """SELECT q.token, q.status, v.is_simulated FROM quotes q
               JOIN vendors v ON v.id = q.vendor_id WHERE q.issue_id = ? ORDER BY q.id""",
            (issue["id"],),
        ).fetchall()
        pick = ([r for r in rows if r["status"] == "accepted"]
                or [r for r in rows if not r["is_simulated"]] or list(rows))
        token = pick[0]["token"] if pick else None
    conn.close()
    if not token:
        return HTMLResponse(
            "<body style='font-family:sans-serif;background:#0a0e1a;color:#e8ebf5;padding:40px'>"
            "<h2>No job yet</h2><p>Submit a tenant report first, then come back to the vendor page.</p>"
            "<a style='color:#7cc0ff' href='/report/OAK12'>Report a problem</a></body>"
        )
    return RedirectResponse(f"/v/{token}", status_code=303)


@app.post("/manager/reset")
def manager_reset():
    if not demo_on():
        raise HTTPException(404, "Not found")
    try:
        for f in os.listdir(agent.UPLOAD_DIR):
            try:
                os.remove(os.path.join(agent.UPLOAD_DIR, f))
            except OSError:
                pass
        seed.run()
    except Exception as e:
        raise HTTPException(500, f"Reset failed: {str(e)[:100]}")
    return RedirectResponse("/manager", status_code=303)