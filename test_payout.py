import os
import time
import httpx
from dotenv import load_dotenv

load_dotenv()

BASE = os.getenv("PAYPAL_BASE", "https://api-m.sandbox.paypal.com")
CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID")
SECRET = os.getenv("PAYPAL_SECRET")
RECEIVER = os.getenv("PAYOUT_TEST_EMAIL")


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


def send_payout(token):
    stamp = str(int(time.time()))
    body = {
        "sender_batch_header": {
            "sender_batch_id": f"test_{stamp}",
            "email_subject": "Mendly test payout",
            "email_message": "Test payment from Mendly",
        },
        "items": [
            {
                "recipient_type": "EMAIL",
                "amount": {"value": "1.00", "currency": "USD"},
                "receiver": RECEIVER,
                "note": "Mendly test job",
                "sender_item_id": f"item_{stamp}",
            }
        ],
    }
    r = httpx.post(
        f"{BASE}/v1/payments/payouts",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    print("Payout status:", r.status_code)
    print(r.text)
    return r


if __name__ == "__main__":
    if not (CLIENT_ID and SECRET and RECEIVER):
        raise SystemExit("Missing PAYPAL_CLIENT_ID, PAYPAL_SECRET or PAYOUT_TEST_EMAIL in .env")
    send_payout(get_token())