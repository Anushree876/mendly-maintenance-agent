<div align="center">

<img src="app/static/logo.png" alt="Mendly" width="88">

# Mendly

**A leaking tap should not take five phone calls to fix.**

An AI agent that turns one tenant photo into a finished, verified and *paid* repair, and never spends a dollar the manager has not allowed.

[Live demo](YOUR_LIVE_URL) · [Demo video](YOUR_YOUTUBE_URL) · Built for the PayPal AI Hackathon

</div>

---

## Why I built this

Every rented home has the same story. The sink leaks, the tenant sends a blurry photo in a group chat, the manager phones three plumbers, someone forgets to reply, nobody is sure the job was done, and then there is a argument about who pays what.

None of that is hard work. It is *chasing*. So I built an agent that does the chasing, and left the one thing that should stay human, the decision to spend money, in the manager's hands.

> **The agent proposes. The manager decides. PayPal moves the money.**

---

## What happens when someone reports a problem

1. **A tenant sends a photo** and one line of text, like "kitchen sink is leaking".
2. **Gemini looks at the photo** and decides the trade (plumbing, electrical, HVAC or general), how urgent it is, a fair cost range and a one-line summary.
3. **The agent invites up to three vendors**, each with a private link. No accounts, no passwords.
4. **Quotes come back** and the agent checks every one against the usual price for that repair. Anything too far above it is flagged and never picked.
5. **The AI picks the best value** from what is left, looking at price, rating and how soon they can start.
6. **Spend Guard decides who approves it.** Under the manager's limit, it is booked automatically. Over the limit, the manager gets an email and approves or rejects it.
7. **The vendor does the work** and uploads an "after" photo.
8. **The tenant is asked "Is it fixed?"** If yes, Gemini compares the before and after photos and gives a confidence score. Confident enough, and the job is verified. Not sure, and it goes to the manager.
9. **The manager approves the payment** and PayPal captures it. The job closes as **Paid**.

Every step is written to an audit trail with *who* did it and *why*, so nothing the agent does is a mystery.

---

## Spend Guard

The part I care about most. The manager sets two rules:

| Rule | What it does |
|---|---|
| **Auto-approve under $X** | Winning quotes at or below this are booked without asking. |
| **Flag quotes above average by Y%** | Quotes too far over the usual price are flagged, and the agent will never pick them. |

Even then, **every payment still needs the manager's own click** on *Approve and pay*. The agent can never pay anyone by itself.

---

## Where PayPal and AI fit

**AI (Google Gemini)**
- Reads the repair photo and returns the trade, urgency, cost range and summary.
- Compares before and after photos and says whether the problem is really fixed, with a confidence score.
- Recommends the best quote from the ones that passed the price rules.
- If Gemini is down or out of quota, the app does not break. It falls back to keyword matching and the lowest fair quote, and says so in the activity log.

**PayPal (Orders v2, sandbox)**
- The manager's "Approve and pay" creates a PayPal order for the exact quoted amount.
- The manager approves it on PayPal's own page, then Mendly captures the payment.
- The order and capture IDs are saved on the job, and the tenant sees "Paid" on their status page.
- Safe against double clicks: each payment attempt uses its own request ID.

Only sandbox money is used. No real money moves.

---

## Three people, three screens

| Who | What they see |
|---|---|
| **Tenant** | A property link like `/report/OAK12`, then a live status page with a progress tracker, the AI scan and a before/after slider. |
| **Vendor** | A private link per job. Send a quote, later upload a completion photo. No login. |
| **Manager** | A password-protected dashboard, a "needs attention" list for stuck jobs, the full audit trail and the Spend Guard rules. |

---

## Try it

### Option 1: the live demo
Open **YOUR_LIVE_URL** and follow the steps in **Demo mode** below.

### Option 2: run it yourself

You need Python 3.12 or newer.

```bash
git clone https://github.com/Anushree876/mendly-maintenance-agent.git
cd mendly-maintenance-agent

python -m venv venv
source venv/Scripts/activate        # Windows (Git Bash)
# source venv/bin/activate          # Mac / Linux

pip install -r requirements.txt
```

Create a file named `.env` in the project folder:

```env
GEMINI_API_KEY=your_gemini_key
GEMINI_MODELS=gemini-3.1-flash-lite,gemini-3.5-flash

PAYPAL_CLIENT_ID=your_sandbox_client_id
PAYPAL_SECRET=your_sandbox_secret
PAYPAL_BASE=https://api-m.sandbox.paypal.com
CURRENCY=USD

MANAGER_PASSWORD=choose_a_password
BASE_URL=http://127.0.0.1:8000
DEMO_MODE=true

# Optional: shows a PayPal sandbox login on the landing page (demo mode only)
DEMO_PAYPAL_EMAIL=
DEMO_PAYPAL_PASSWORD=

# Optional: real emails to vendors and the manager
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=
SMTP_PASS=
REAL_VENDOR_EMAIL=
MANAGER_EMAIL=
# or use Resend instead of SMTP
RESEND_API_KEY=
```

Load the starting data, then run the app:

```bash
python -m app.seed
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000

Where to get the keys:
- Gemini key: https://aistudio.google.com/apikey
- PayPal sandbox keys and a test buyer account: https://developer.paypal.com (Apps and Credentials, and Testing tools)

---

## Demo mode

With `DEMO_MODE=true`, the app is easy to walk through alone:

1. On the landing page, click **Report a problem**, tap **Use a sample photo** and submit.
2. On the status page, watch the AI scan. Two simulated vendors reply on their own within seconds.
3. Open **Demo tools** and click **Bid as demo vendor** to quote as the third vendor.
4. If the winning quote is over the limit, click **Open manager view** and approve it.
5. Use **Selected vendor link** to open the vendor page and upload the sample after photo.
6. Back on the status page, drag the before/after slider and click **Yes, fixed**.
7. As the manager, click **Pay** and log in with the PayPal sandbox buyer shown on the landing page.
8. The status page turns to **Paid**.

The manager dashboard has a **Reset demo data** button to start fresh.

With `DEMO_MODE=false`, the shortcuts disappear. The manager signs in with a password and vendors receive their links by email.

---

## Built with

- **Python and FastAPI** for the backend
- **Jinja2 templates** and plain CSS for the interface
- **SQLite** for storage
- **Google Gemini** (vision and text) for photo analysis, fix verification and quote comparison
- **PayPal Orders v2 (sandbox)** for payments
- **Pillow** for image handling, **httpx** for HTTP, **Resend or SMTP** for email

I built this with AI coding assistance, and I tested every flow by hand.

---

## Honest limits

- Most vendors in the demo are **simulated**. The vendor page and the payment are real.
- It uses a single SQLite file, which is fine for a demo but not for many managers at once.
- PayPal runs in **sandbox** only.
- Vendors are paid through a normal PayPal order today. Paying vendors directly to their own PayPal account is the next step.

## What I would build next

- Pay each vendor straight to their own PayPal account
- Vendor sign-up and trade verification
- WhatsApp and SMS instead of email
- Repeat-issue detection, so a tap that keeps leaking raises a flag
- Multiple managers and many properties

---

## Project layout

```
app/
  main.py        routes, login, demo helpers
  agent.py       the workflow: invite, compare, approve, verify, pay
  ai.py          Gemini calls, with keyword fallback
  paypal.py      create and capture PayPal orders
  mailer.py      email through Resend or SMTP
  db.py          database and status names
  seed.py        demo data
  templates/     all pages
  static/        styles, logo, sample photos
```

---

## License

MIT. See [LICENSE](LICENSE).

<div align="center">

Made by **Anushree Gupta** · [@Anushree876](https://github.com/Anushree876)

</div>
