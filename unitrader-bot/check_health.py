import httpx

BASE = "https://api.unitrader.ai"

for path in ["/health", "/health/database", "/health/ai"]:
    try:
        r = httpx.get(f"{BASE}{path}", timeout=15, follow_redirects=True)
        print(f"{path}: {r.status_code} — {r.text[:300]}")
    except Exception as e:
        print(f"{path}: ERROR — {e}")
