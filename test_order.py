import os
import time
import httpx
from dotenv import load_dotenv

load_dotenv()

BASE = os.getenv("PAYPAL_BASE", "https://api-m.sandbox.paypal.com")
CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID")
SECRET = os.getenv("PAYPAL_SECRET")
CURRENCY = os.getenv("CURRENCY", "USD")
PAYEE = os.getenv("PAYEE_EMAIL", "").strip()


def get_token():
    r = httpx.post(
        f"{BASE}/v1/oauth2/token",
        auth=(CLIENT_ID, SECRET),
        data={"grant_type": "client_credentials"},
        timeout=30,
    )
    print("Token status:", r.status_code)
    r.raise_for_status()
    return r.json()["access_token"]


def create_order(token):
    unit = {
        "reference_id": f"job_{int(time.time())}",
        "description": "Mendly test repair job",
        "amount": {"currency_code": CURRENCY, "value": "5.00"},
    }
    if PAYEE:
        unit["payee"] = {"email_address": PAYEE}
    body = {
        "intent": "CAPTURE",
        "purchase_units": [unit],
        "application_context": {
            "return_url": "https://example.com/return",
            "cancel_url": "https://example.com/cancel",
            "user_action": "PAY_NOW",
        },
    }
    r = httpx.post(
        f"{BASE}/v2/checkout/orders",
        json=body,
        headers={
            "Authorization": f"Bearer {token}",
            "PayPal-Request-Id": f"mendly-{int(time.time())}",
        },
        timeout=30,
    )
    print("Create order status:", r.status_code)
    print(r.text)
    r.raise_for_status()
    return r.json()


def capture_order(token, order_id):
    r = httpx.post(
        f"{BASE}/v2/checkout/orders/{order_id}/capture",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        timeout=30,
    )
    print("Capture status:", r.status_code)
    print(r.text)
    return r


if __name__ == "__main__":
    if not (CLIENT_ID and SECRET):
        raise SystemExit("Missing PayPal keys in .env")
    token = get_token()
    order = create_order(token)
    approve = next(l["href"] for l in order["links"] if l["rel"] in ("approve", "payer-action"))
    print("\nOpen this link, log in with your sandbox PERSONAL account, and approve:")
    print(approve)
    input("\nPress Enter after you approve the payment...")
    capture_order(token, order["id"])