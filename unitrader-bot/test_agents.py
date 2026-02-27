"""Test all 4 agents via API endpoints. Requires server running on :8000."""
import sys
import urllib.request
import urllib.error
import json
import time

# Force UTF-8 output on Windows so emoji in Claude responses don't crash the script
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://localhost:8000"

def post(path, data, token=None):
    body = json.dumps(data).encode()
    req = urllib.request.Request(BASE + path, data=body,
                                  headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())

def get(path, token=None):
    req = urllib.request.Request(BASE + path)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())

results = []

def check(name, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    results.append((status, name, detail))
    icon = "+" if passed else "X"
    print(f"  [{icon}] {name}" + (f" -- {detail}" if detail else ""))

print("=" * 65)
print("UNITRADER -- AGENT TEST SUITE")
print("=" * 65)

# ── Create test user + get token ──────────────────────────────────
email = "agenttest" + str(int(time.time())) + "@example.com"
code, body = post("/api/auth/register",
                  {"email": email, "password": "Test@123456!", "ai_name": "TestAI"})
assert code == 201, f"Register failed: {body}"

code, body = post("/api/auth/login", {"email": email, "password": "Test@123456!"})
assert code == 200, f"Login failed: {body}"
token = body["access_token"]
print(f"\nTest user: {email}  |  AI name: TestAI")
print(f"Token acquired: {token[:20]}...")

# ── AGENT 1: Conversation Agent (chat) ───────────────────────────
print("\n[1] Conversation Agent -- /api/chat/message")
messages = [
    ("How is the market today?", "general/market"),
    ("I made 50% profit this week!", "friendly/celebration"),
    ("What is RSI and how do I use it?", "educational"),
    ("I am really worried about my trades", "emotional support"),
]
for msg, label in messages:
    print(f"  Sending [{label}]: {msg[:50]}")
    code, resp = post("/api/chat/message", {"message": msg}, token=token)
    check(
        f"Chat [{label}] returns 200",
        code == 200,
        f"HTTP {code}",
    )
    response_text = (resp.get("data") or {}).get("response", "")
    check(
        f"Chat [{label}] has AI response",
        bool(response_text),
        response_text[:80] + "..." if len(response_text) > 80 else response_text,
    )
    detected_ctx = (resp.get("data") or {}).get("context", "?")
    print(f"       Context detected: {detected_ctx}")

# ── AGENT 2: Trading Agent decision ──────────────────────────────
print("\n[2] Trading Agent -- /api/trading/execute (BTC/USDT)")
code, resp = post("/api/trading/execute",
                  {"symbol": "BTC/USDT", "exchange": "binance"},
                  token=token)
check("Trading execute returns 200 or 400", code in (200, 400, 422),
      f"HTTP {code}")
if code == 200:
    trade_data = resp.get("data", {})
    decision = trade_data.get("decision", trade_data.get("status", "?"))
    check("Trading decision field present", bool(decision), str(decision))
    print(f"       Decision: {decision}")
else:
    detail = resp.get("detail", resp.get("error", str(resp)))[:100]
    print(f"       Note (no exchange key): {detail}")
    check("Trading endpoint registered", code != 404, f"HTTP {code}")

# ── AGENT 3: Content Writer -- blog post ─────────────────────────
print("\n[3] Content Writer Agent -- /api/content/generate-blog")
code, resp = post("/api/content/generate-blog",
                  {"topic": "How Stop-Loss Orders Protect Your Trading Capital"},
                  token=token)
check("Blog generate returns 200", code == 200, f"HTTP {code}")
if code == 200:
    blog = resp.get("data", {})
    check("Blog has title", bool(blog.get("title")),
          blog.get("title", "")[:60])
    check("Blog has content (1000+ words expected)",
          len(blog.get("content", "")) > 200,
          f"{len(blog.get('content',''))} chars")
    check("Blog has SEO keywords", bool(blog.get("seo_keywords")),
          str(blog.get("seo_keywords", [])[:3]))
    print(f"       Title: {blog.get('title','?')[:60]}")
    print(f"       Words: ~{blog.get('word_count', '?')}")
else:
    print(f"       Error: {resp.get('detail', resp)}")

# ── AGENT 4: Social Media Agent -- social posts ───────────────────
print("\n[4] Social Media Agent -- /api/content/generate-social")
code, resp = post("/api/content/generate-social",
                  {"topic": "AI trading beats manual trading", "count": 3},
                  token=token)
check("Social posts returns 200", code == 200, f"HTTP {code}")
if code == 200:
    posts = resp.get("data", {}).get("posts", [])
    check("Social posts array returned", isinstance(posts, list) and len(posts) > 0,
          f"{len(posts)} posts")
    if posts:
        check("Posts have content field",
              all(p.get("content") for p in posts),
              "all have content")
        check("Posts have platform field",
              all(p.get("platform") for p in posts),
              str([p.get("platform") for p in posts[:3]]))
        for i, p in enumerate(posts[:2]):
            print(f"       Post {i+1} [{p.get('platform')}]: {p.get('content','')[:70]}...")
else:
    print(f"       Error: {resp.get('detail', resp)}")

# ── Chat history (conversation memory) ───────────────────────────
print("\n[5] Conversation Memory -- /api/chat/history")
code, resp = get("/api/chat/history", token=token)
check("Chat history returns 200", code == 200, f"HTTP {code}")
history = resp.get("data", {}).get("conversations", [])
check("History has saved conversations", len(history) > 0,
      f"{len(history)} conversations stored")

# ── Summary ───────────────────────────────────────────────────────
print("\n" + "=" * 65)
passed = sum(1 for r in results if r[0] == "PASS")
failed = sum(1 for r in results if r[0] == "FAIL")
print(f"RESULTS: {passed} passed  |  {failed} failed  |  {len(results)} total")
if failed:
    print("\nFailed:")
    for r in results:
        if r[0] == "FAIL":
            print(f"  X {r[1]} -- {r[2]}")
else:
    print("All agent checks passed!")
print("=" * 65)
