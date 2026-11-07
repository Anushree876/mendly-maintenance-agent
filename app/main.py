import os
import uuid

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image

from app import agent, db

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(title="Mendly")
os.makedirs(agent.UPLOAD_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


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
def home():
    return RedirectResponse("/report/OAK12")


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
    photo: UploadFile = File(...),
    message: str = Form(...),
    tenant_name: str = Form("Tenant"),
):
    conn = db.get_conn()
    prop = conn.execute("SELECT * FROM properties WHERE code = ?", (code,)).fetchone()
    if not prop:
        conn.close()
        raise HTTPException(404, "Property not found")

    try:
        photo_name = save_photo(photo)
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
    return RedirectResponse(f"/status/{issue_id}", status_code=303)


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
         "quotes": quotes, "base_url": base_url},
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
        {"quote": quote, "issue": issue, "property": dict(prop)},
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