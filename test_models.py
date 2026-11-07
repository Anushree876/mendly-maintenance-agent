import os
from dotenv import load_dotenv
from google import genai

load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
for m in os.getenv("GEMINI_MODELS", "").split(","):
    m = m.strip()
    try:
        r = client.models.generate_content(model=m, contents="Reply with the word OK")
        print(m, "->", r.text.strip()[:20])
    except Exception as e:
        print(m, "-> FAILED:", str(e)[:90])