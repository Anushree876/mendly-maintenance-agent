import io
import json
import os
import time

from dotenv import load_dotenv
from PIL import Image

from app import db

load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
MODELS = [m.strip() for m in os.getenv("GEMINI_MODELS", MODEL).split(",") if m.strip()]

ALLOWED_TYPES = ["plumbing", "electrical", "hvac", "general"]
ALLOWED_URGENCY = ["low", "medium", "high"]

KEYWORDS = {
    "plumbing": ["leak", "sink", "tap", "faucet", "toilet", "pipe", "drain", "water", "clog"],
    "electrical": ["light", "outlet", "socket", "switch", "power", "wire", "spark", "fuse"],
    "hvac": ["ac", "a/c", "heater", "heating", "cooling", "furnace", "thermostat", "vent"],
}


def prepare_image(path, max_side=1024):
    """Resize to max 1024px and return JPEG bytes."""
    img = Image.open(path).convert("RGB")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()



def call_llm(prompt, image_paths=None, tries=2):
    """Call Gemini, trying each model in MODELS. Returns parsed JSON (dict) or None."""
    if not API_KEY:
        return None
    from google import genai
    from google.genai import types

    parts = []
    for p in image_paths or []:
        parts.append(types.Part.from_bytes(data=prepare_image(p), mime_type="image/jpeg"))
    parts.append(prompt)

    client = genai.Client(api_key=API_KEY)
    for model in MODELS:
        for attempt in range(tries):
            try:
                resp = client.models.generate_content(
                    model=model,
                    contents=parts,
                    config=types.GenerateContentConfig(response_mime_type="application/json"),
                )
                return json.loads(resp.text)
            except Exception as e:
                print(f"[ai] {model} attempt {attempt + 1} failed: {str(e)[:100]}")
                time.sleep(1 + attempt)
    return None

def _fallback(message):
    text = (message or "").lower()
    rtype = "general"
    for t, words in KEYWORDS.items():
        if any(w in text for w in words):
            rtype = t
            break
    avg = db.get_avg_price(rtype) or 120
    return {
        "repair_type": rtype,
        "urgency": "medium",
        "est_low": round(avg * 0.7),
        "est_high": round(avg * 1.5),
        "summary": "Estimated from the tenant's message (AI was unavailable).",
    }


def analyze_issue(photo_fs_path, message):
    """Returns (result_dict, used_ai)."""
    prompt = f"""You analyze property maintenance photos for a property manager.
Tenant message: "{message}"
Reply with JSON only, with exactly these keys:
repair_type (one of: plumbing, electrical, hvac, general),
urgency (one of: low, medium, high),
est_low (number, USD),
est_high (number, USD),
summary (one short sentence describing the problem)."""

    data = call_llm(prompt, [photo_fs_path])
    if not data:
        return _fallback(message), False
    try:
        rtype = data.get("repair_type", "general")
        urgency = data.get("urgency", "medium")
        result = {
            "repair_type": rtype if rtype in ALLOWED_TYPES else "general",
            "urgency": urgency if urgency in ALLOWED_URGENCY else "medium",
            "est_low": float(data.get("est_low", 0)),
            "est_high": float(data.get("est_high", 0)),
            "summary": str(data.get("summary", ""))[:300],
        }
        return result, True
    except (TypeError, ValueError):
        return _fallback(message), False