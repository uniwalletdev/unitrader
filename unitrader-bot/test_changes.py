"""Comprehensive tests for: pricing fix + Clerk endpoints + auth flow."""
import urllib.request
import urllib.error
import json
import time

BASE = "http://localhost:8000"

def get(path, token=None):
    req = urllib.request.Request(BASE + path)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())

def post(path, data, token=None):
    body = json.dumps(data).encode()
    req = urllib.request.Request(BASE + path, data=body,
                                  headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
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
print("UNITRADER -- POST-CHANGE TEST SUITE")
print("=" * 65)

# ── TEST 1: Health ────────────────────────────────────────────────
print("\n[1] Health check")
code, body = get("/health")
check("Server reachable", code == 200, f"HTTP {code}")
check("Status = healthy", body.get("status") == "healthy", body.get("status", "?"))

# ── TEST 2: Pricing ───────────────────────────────────────────────
print("\n[2] Pricing endpoint -- expecting $9.99/mo")
code, body = get("/api/billing/plans")
check("GET /api/billing/plans returns 200", code == 200, f"HTTP {code}")
plans = body.get("data", {}).get("plans", [])
pro = next((p for p in plans if p["id"] == "pro"), None)
free = next((p for p in plans if p["id"] == "free"), None)
if pro:
    check("Pro price = $9.99", pro["price_usd"] == 9.99, f"${pro['price_usd']}")
    check("Pro price_cents = 999 (Stripe)", pro["price_monthly_cents"] == 999,
          str(pro["price_monthly_cents"]))
    check("Free plan still $0", free is not None and free["price_usd"] == 0,
          "$0" if free else "not found")
    check("7-day trial included", pro.get("trial_days") == 7,
          str(pro.get("trial_days")))
else:
    check("Pro plan exists in response", False, "not found")

# ── TEST 3: Clerk sync ────────────────────────────────────────────
print("\n[3] Clerk /api/auth/clerk-sync")
code, body = post("/api/auth/clerk-sync", {"clerk_token": "bad.token"})
# Endpoint is registered if we get 401 (invalid token) not 404 (not found)
check("Endpoint registered (not 404)", code != 404, f"HTTP {code}")
check("Invalid token -> 401", code == 401,
      body.get("detail", str(body))[:80])

# ── TEST 4: Clerk setup ───────────────────────────────────────────
print("\n[4] Clerk /api/auth/clerk-setup")
# Send valid format but non-existent user_id -- should get 404 USER not found,
# which proves the endpoint is registered and executing our code
code, body = post("/api/auth/clerk-setup",
                  {"user_id": "00000000-0000-0000-0000-000000000000",
                   "ai_name": "TestAI"})
check("Endpoint registered (not 405 method not allowed)", code != 405, f"HTTP {code}")
check("Runs our code (user not found = 404)", code == 404,
      body.get("detail", str(body))[:60])

# Invalid AI name (special chars)
code, body = post("/api/auth/clerk-setup",
                  {"user_id": "00000000-0000-0000-0000-000000000000",
                   "ai_name": "inv@lid!"})
check("Invalid AI name -> 422", code == 422,
      body.get("detail", str(body))[:60])

# ── TEST 5: Register + Login ──────────────────────────────────────
print("\n[5] Email/password auth flow")
email = "tester" + str(int(time.time())) + "@example.com"
code, body = post("/api/auth/register",
                  {"email": email, "password": "Test@123456!", "ai_name": "RegBot"})
# Register correctly returns 201 Created
check("Register returns 201", code == 201, f"HTTP {code}")
check("Register body status=success", body.get("status") == "success",
      body.get("status", body.get("detail", "?"))[:60])

code, body = post("/api/auth/login",
                  {"email": email, "password": "Test@123456!"})
check("Login returns 200", code == 200, f"HTTP {code}")
check("Login body status=logged_in", body.get("status") == "logged_in",
      body.get("status", "?"))

# Token is at top level (not nested in data)
token = body.get("access_token")
check("Access token present", bool(token), "present" if token else "missing")

if token:
    code, me = get("/api/auth/me", token=token)
    check("GET /api/auth/me with JWT returns 200", code == 200, f"HTTP {code}")
    check("Me email correct", me.get("email") == email, me.get("email", "?")[:40])
    check("Me ai_name = RegBot", me.get("ai_name") == "RegBot",
          me.get("ai_name", "?"))

    # ── TEST 6: Billing status (authenticated) ─────────────────────
    print("\n[6] Billing status (authenticated user)")
    code, billing = get("/api/billing/status", token=token)
    check("GET /api/billing/status returns 200", code == 200, f"HTTP {code}")
    tier = (billing.get("data") or {}).get("tier")
    check("New user tier = free", tier == "free", str(tier))

    # ── TEST 7: Chat endpoint ──────────────────────────────────────
    print("\n[7] Chat endpoint")
    code, chat = post("/api/chat/message",
                      {"message": "How is the market today?"}, token=token)
    check("POST /api/chat/message returns 200", code == 200, f"HTTP {code}")
    has_response = bool((chat.get("data") or {}).get("response"))
    check("AI response returned", has_response,
          "present" if has_response else "missing")

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
    print("All checks passed!")
print("=" * 65)
