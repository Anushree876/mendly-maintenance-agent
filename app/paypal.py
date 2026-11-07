import os
import time

import httpx
from dotenv import load_dotenv

load_dotenv()

BASE = os.getenv("PAYPAL_BASE", "https://api-m.sandbox.paypal.com")
CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID")
SECRET = os.getenv("PAYPAL_SECRET")
CURRENCY = os.getenv("CURRENCY", "USD")

_token = {"value": None, "expires": 0}


def get_token():
    if _token["value"] and time.time() < _token["expires"] - 60:
        return _token["value"]
    r = httpx.post(
        f"{BASE}/v1/oauth2/token",
        auth=(CLIENT_ID, SECRET),
        data={"grant_type": "client_credentials"},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    _token["value"] = data["access_token"]
    _token["expires"] = time.time() + int(data.get("expires_in", 300))
    return _token["value"]


def _headers(extra=None):
    h = {"Authorization": f"Bearer {get_token()}", "Content-Type": "application/json"}
    if extra:
        h.update(extra)
    return h


def create_order(amount, issue_id, request_id, return_url, cancel_url, description):
    body = {
        "intent": "CAPTURE",
        "purchase_units": [{
            "reference_id": f"issue_{issue_id}",
            "description": description[:120],
            "amount": {"currency_code": CURRENCY, "value": f"{amount:.2f}"},
        }],
        "application_context": {
            "return_url": return_url,
            "cancel_url": cancel_url,
            "user_action": "PAY_NOW",
            "brand_name": "Mendly",
        },
    }
    r = httpx.post(
        f"{BASE}/v2/checkout/orders",
        json=body,
        headers=_headers({"PayPal-Request-Id": request_id}),
        timeout=30,
    )
    r.raise_for_status()
    order = r.json()
    approve = next(
        l["href"] for l in order["links"] if l["rel"] in ("approve", "payer-action")
    )
    return order["id"], approve


def capture_order(order_id):
    """Returns (http_status, json). Does not raise, so the caller can handle 422."""
    r = httpx.post(
        f"{BASE}/v2/checkout/orders/{order_id}/capture",
        headers=_headers(),
        timeout=30,
    )
    return r.status_code, r.json()


def get_order(order_id):
    r = httpx.get(f"{BASE}/v2/checkout/orders/{order_id}", headers=_headers(), timeout=30)
    r.raise_for_status()
    return r.json()


def capture_id_from(order_json):
    try:
        return order_json["purchase_units"][0]["payments"]["captures"][0]["id"]
    except (KeyError, IndexError, TypeError):
        return None