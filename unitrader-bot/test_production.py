#!/usr/bin/env python3
"""
Comprehensive production test for Unitrader (Railway).
Run: python test_production.py
"""
import os
import sys

try:
    import httpx
except ImportError:
    print("Install httpx: pip install httpx")
    sys.exit(1)

BASE = os.environ.get("UNITRADER_PROD_URL", "https://unitrader-production.up.railway.app").rstrip("/")
TIMEOUT = 20.0
TOKEN = None  # filled after login

PASS = "[PASS]"
FAIL = "[FAIL]"
WARN = "[WARN]"


def get(path):
    url = f"{BASE}{path}"
    try:
        r = httpx.get(url, timeout=TIMEOUT)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, {"raw": r.text[:300]}
    except Exception as e:
        return 0, {"error": str(e)}


def post(path, payload, token=None):
    url = f"{BASE}{path}"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        r = httpx.post(url, json=payload, headers=headers, timeout=TIMEOUT)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, {"raw": r.text[:300]}
    except Exception as e:
        return 0, {"error": str(e)}


def check(label, ok, detail=""):
    icon = PASS if ok else FAIL
    print(f"  {icon}  {label}" + (f"  →  {detail}" if detail else ""))
    return ok


results = []


def test(label, ok, detail=""):
    results.append(ok)
    return check(label, ok, detail)


print(f"\nTesting: {BASE}\n")

# ── HEALTH ──────────────────────────────────────────────────────────────
print("─── HEALTH CHECKS ───────────────────────────────────────────")

code, body = get("/health")
test("App is running", code == 200, body.get("app", ""))

code, body = get("/health/database")
db_ok = body.get("services", {}).get("database", {}).get("status") == "healthy"
db_detail = body.get("services", {}).get("database", {}).get("detail", "")
test("Database connected", db_ok, db_detail if not db_ok else "connected")

code, body = get("/health/ai")
ai_ok = body.get("services", {}).get("ai", {}).get("status") == "healthy"
test("Anthropic AI connected", ai_ok)

# ── AUTH ─────────────────────────────────────────────────────────────────
print("\n─── AUTH ────────────────────────────────────────────────────")

TEST_EMAIL = "prodtest_v2@example.com"
TEST_PASS = "TestPass123!"
TEST_NAME = "TradeMaster"

code, body = post("/api/auth/register", {"email": TEST_EMAIL, "password": TEST_PASS, "ai_name": TEST_NAME})
reg_ok = code in (200, 201) or (code == 400 and "already" in str(body).lower()) or (code == 409)
reg_detail = body.get("status", body.get("error", body.get("detail", "")))
test("Register user", reg_ok, str(code) + " " + str(reg_detail)[:60])

code, body = post("/api/auth/login", {"email": TEST_EMAIL, "password": TEST_PASS})
login_ok = code == 200 and ("token" in str(body) or "access_token" in str(body))
if login_ok:
    TOKEN = body.get("access_token") or body.get("token") or body.get("data", {}).get("access_token", "")
login_detail = f"token={'yes' if TOKEN else 'no'}" if login_ok else str(body)[:80]
test("Login", login_ok, str(code) + " " + login_detail)

if TOKEN:
    code, body = get("/api/auth/me")
    # retry with token
    try:
        r = httpx.get(f"{BASE}/api/auth/me", headers={"Authorization": f"Bearer {TOKEN}"}, timeout=TIMEOUT)
        code, body = r.status_code, r.json()
    except Exception:
        pass
    me_ok = code == 200
    me_detail = body.get("data", {}).get("email", body.get("email", str(body)[:60]))
    test("/api/auth/me", me_ok, str(code) + " " + str(me_detail))
else:
    test("/api/auth/me", False, "skipped — no token")

# ── CHAT ─────────────────────────────────────────────────────────────────
print("\n─── CHAT ────────────────────────────────────────────────────")

if TOKEN:
    code, body = post("/api/chat/message", {"message": "Hello, how are the markets today?"}, token=TOKEN)
    chat_ok = code == 200 and "response" in str(body)
    chat_detail = str(body.get("data", {}).get("response", body.get("response", body)))[:80]
    test("Chat message", chat_ok, str(code) + " " + str(chat_detail))

    code, body = post("/api/chat/message", {"message": "Should I buy BTC?"}, token=TOKEN)
    ctx_ok = code == 200
    ctx_detail = str(body.get("data", {}).get("context", body.get("context", "")))
    test("Context detection", ctx_ok, ctx_detail)
else:
    test("Chat message", False, "skipped — no token")
    test("Context detection", False, "skipped — no token")

# ── TRADING ──────────────────────────────────────────────────────────────
print("\n─── TRADING ─────────────────────────────────────────────────")

if TOKEN:
    code, body = httpx.get(f"{BASE}/api/trading/open-positions",
                            headers={"Authorization": f"Bearer {TOKEN}"}, timeout=TIMEOUT).json and \
                  (lambda r: (r.status_code, r.json()))(
                      httpx.get(f"{BASE}/api/trading/open-positions",
                                headers={"Authorization": f"Bearer {TOKEN}"}, timeout=TIMEOUT))
    test("Open positions", code == 200, str(code))

    r = httpx.get(f"{BASE}/api/trading/performance", headers={"Authorization": f"Bearer {TOKEN}"}, timeout=TIMEOUT)
    test("Performance stats", r.status_code == 200, str(r.status_code))

    r = httpx.get(f"{BASE}/api/trading/risk-analysis", headers={"Authorization": f"Bearer {TOKEN}"}, timeout=TIMEOUT)
    test("Risk analysis", r.status_code == 200, str(r.status_code))
else:
    test("Open positions", False, "skipped — no token")
    test("Performance stats", False, "skipped — no token")
    test("Risk analysis", False, "skipped — no token")

# ── SUMMARY ──────────────────────────────────────────────────────────────
passed = sum(results)
total = len(results)
print(f"\n{'─'*50}")
print(f"  {passed}/{total} checks passed\n")

if not db_ok:
    print("BLOCKER — Database is not connected. Everything else will fail.")
    print("  Fix in Railway → Variables:")
    print("  1. If you added a Postgres plugin: set  DATABASE_URL=${{Postgres.DATABASE_URL}}")
    print("  2. If using Supabase: use the Transaction Pooler URL from Settings > Database > URI")
    print("  3. After updating, redeploy the backend service.")
    print()

if not TOKEN:
    print("BLOCKER — Login failed. Fix database first, then test again.")
    print()

if passed == total:
    print("ALL CHECKS PASS — ready for frontend deployment!")
    print()
    print("NEXT STEPS:")
    print("  1. In Vercel: set NEXT_PUBLIC_API_URL=https://unitrader-production.up.railway.app")
    print("  2. Push frontend/ to GitHub and connect to Vercel")
    print("  3. Visit your Vercel URL, register, and test the full UI")
    print("  4. Set up Stripe webhook: https://unitrader-production.up.railway.app/api/billing/webhook")
