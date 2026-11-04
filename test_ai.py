import os
import json
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

PROMPT = """You analyze property maintenance photos.
Tenant message: "Kitchen sink is leaking from the faucet."
Reply with JSON only, with exactly these keys:
repair_type (one of: plumbing, electrical, hvac, general),
urgency (one of: low, medium, high),
est_low (number, USD),
est_high (number, USD),
summary (one short sentence)."""

if __name__ == "__main__":
    if not API_KEY:
        raise SystemExit("Missing GEMINI_API_KEY in .env")

    with open("sample.jpg", "rb") as f:
        img = f.read()

    client = genai.Client(api_key=API_KEY)
    response = client.models.generate_content(
        model=MODEL,
        contents=[
            types.Part.from_bytes(data=img, mime_type="image/jpeg"),
            PROMPT,
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json"
        ),
    )
    print("Raw:", response.text)
    data = json.loads(response.text)
    print("Parsed:", data)