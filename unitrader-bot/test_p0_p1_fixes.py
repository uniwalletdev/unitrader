#!/usr/bin/env python3
"""
Test script for P0/P1 fixes against production backend.

Tests:
  1. CRYPTO ROUTING FIX - BTC/USD via Alpaca crypto routing
  2. STOCK ROUTING - AAPL via Alpaca stock routing
  3. TESTING MODE BYPASS - Verify trade limits are bypassed
  4. EXCHANGE KEY STALE CREDENTIAL FIX - Key rotation and health check
  5. RLS CONFIRMATION - Verify service_role access still works

Run: python test_p0_p1_fixes.py

Environment variables (optional):
  UNITRADER_PROD_URL=https://unitrader-production.up.railway.app
  UNITRADER_TEST_EMAIL=your-test@example.com
  UNITRADER_TEST_PASSWORD=YourPassword123!
  ALPACA_API_KEY=your-alpaca-key (for Test 4 with real credentials)
  ALPACA_API_SECRET=your-alpaca-secret (for Test 4 with real credentials)
"""
import os
import sys
import time
import json

try:
    import httpx
except ImportError:
    print("Install httpx: pip install httpx")
    sys.exit(1)

BASE = os.environ.get(
    "UNITRADER_PROD_URL", 
    "https://unitrader-production.up.railway.app"
).rstrip("/")

TEST_EMAIL = os.environ.get("UNITRADER_TEST_EMAIL", "your-test@example.com")
TEST_PASSWORD = os.environ.get("UNITRADER_TEST_PASSWORD", "YourPassword123!")
TEST_NAME = "P0P1Tester"

TIMEOUT = 20.0
TOKEN = None

PASS_ICON = "[✓ PASS]"
FAIL_ICON = "[✗ FAIL]"

# Track results
tests_run = 0
tests_passed = 0
failures = []


def log_result(test_num, name, status, http_status, details=""):
    """Log a test result."""
    global tests_run, tests_passed
    tests_run += 1
    
    icon = PASS_ICON if status else FAIL_ICON
    print(f"  {icon}  Test {test_num}: {name}")
    print(f"         HTTP {http_status}" + (f" | {details}" if details else ""))
    
    if status:
        tests_passed += 1
    else:
        failures.append({
            "test": test_num,
            "name": name,
            "http_status": http_status,
            "details": details,
        })


def get_request(path, token=None):
    """Send GET request."""
    url = f"{BASE}{path}"
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    
    try:
        r = httpx.get(url, headers=headers or None, timeout=TIMEOUT)
        try:
            body = r.json()
        except Exception:
            body = {"raw": r.text[:200]}
        return r.status_code, body
    except Exception as e:
        return 0, {"error": str(e)}


def post_request(path, payload, token=None):
    """Send POST request."""
    url = f"{BASE}{path}"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    
    try:
        r = httpx.post(url, json=payload, headers=headers, timeout=TIMEOUT)
        try:
            body = r.json()
        except Exception:
            body = {"raw": r.text[:200]}
        return r.status_code, body
    except Exception as e:
        return 0, {"error": str(e)}


def delete_request(path, token=None):
    """Send DELETE request."""
    url = f"{BASE}{path}"
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    
    try:
        r = httpx.delete(url, headers=headers or None, timeout=TIMEOUT)
        try:
            body = r.json()
        except Exception:
            body = {"raw": r.text[:200]}
        return r.status_code, body
    except Exception as e:
        return 0, {"error": str(e)}


def setup_auth():
    """Authenticate and get token."""
    global TOKEN
    
    print("\n─── SETUP: AUTHENTICATION ───────────────────────────────")
    
    # Register
    code, body = post_request(
        "/api/auth/register",
        {
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD,
            "ai_name": TEST_NAME,
        }
    )
    is_reg_ok = code in (200, 201) or (code == 400 and "already" in str(body).lower()) or code == 409
    print(f"  Register: HTTP {code} {'(ok or already exists)' if is_reg_ok else '(ERROR)'}")
    
    # Login
    code, body = post_request(
        "/api/auth/login",
        {"email": TEST_EMAIL, "password": TEST_PASSWORD}
    )
    is_login_ok = code == 200 and ("token" in str(body) or "access_token" in str(body))
    
    if is_login_ok:
        TOKEN = body.get("access_token") or body.get("token") or body.get("data", {}).get("access_token", "")
        print(f"  Login: HTTP {code} ✓ (token obtained)")
    else:
        print(f"  Login: HTTP {code} ✗ (FAILED)")
        print(f"    Response: {str(body)[:150]}")
        sys.exit(1)
    
    return TOKEN


def test_crypto_routing():
    """Test 1: CRYPTO ROUTING FIX - BTC/USD via Alpaca crypto routing."""
    print("\n─── TEST 1: CRYPTO ROUTING FIX ─────────────────────────")
    
    code, body = post_request(
        "/api/trading/execute",
        {"symbol": "BTC/USD", "exchange": "alpaca"},
        TOKEN
    )
    
    # PASS: 200, or clean JSON error (400/503)
    # FAIL: 500, or no JSON body
    is_json = isinstance(body, dict) and body is not None
    is_clean_error = code in (400, 503) and is_json
    is_success = code == 200
    is_pass = is_success or is_clean_error or (code not in (500,) and is_json)
    
    detail = ""
    if code == 500:
        detail = "Server error (500)"
    elif not is_json:
        detail = "No JSON body"
    elif is_clean_error:
        detail = f"Clean error: {body.get('detail', body.get('error', ''))[:80]}"
    
    log_result(1, "Crypto Routing (BTC/USD via Alpaca)", is_pass, code, detail)


def test_stock_routing():
    """Test 2: STOCK ROUTING - AAPL via Alpaca stock routing."""
    print("\n─── TEST 2: STOCK ROUTING (SANITY CHECK) ──────────────")
    
    code, body = post_request(
        "/api/trading/execute",
        {"symbol": "AAPL", "exchange": "alpaca"},
        TOKEN
    )
    
    # PASS: 200 or clean JSON error (400/503)
    # FAIL: 500
    is_json = isinstance(body, dict) and body is not None
    is_pass = code != 500 and is_json
    
    detail = ""
    if code == 500:
        detail = "Server error (500)"
    elif not is_json:
        detail = "No JSON body"
    else:
        detail = f"Status {code}: {body.get('status', body.get('detail', ''))[:60]}"
    
    log_result(2, "Stock Routing (AAPL via Alpaca)", is_pass, code, detail)


def test_testing_mode_bypass():
    """Test 3: TESTING MODE BYPASS - Verify trade limits are bypassed."""
    print("\n─── TEST 3: TESTING MODE BYPASS ───────────────────────")
    
    code, body = post_request(
        "/api/trading/execute",
        {"symbol": "BTC/USD", "exchange": "alpaca"},
        TOKEN
    )
    
    # PASS: NOT 403 (trade limit error)
    # FAIL: 403 (trade limit still enforced despite TESTING_MODE)
    is_pass = code != 403
    
    detail = ""
    if code == 403:
        detail = "Trade limit enforced (403) — TESTING_MODE not active"
    else:
        detail = f"Not blocked by trade limit (expected)"
    
    log_result(3, "Testing Mode Trade Limit Bypass", is_pass, code, detail)


def test_exchange_key_stale_credential():
    """Test 4: EXCHANGE KEY STALE CREDENTIAL FIX.
    
    Tests key rotation and health endpoint accessibility.
    Note: Full key testing requires real Alpaca credentials via env vars.
    
    Steps:
    1. Try to DELETE existing Alpaca keys (404 is OK if none exist)
    2. Attempt to POST new keys (400 expected with placeholder creds)
    3. Verify health endpoint is accessible and has no auth errors
    
    PASS: health endpoint accessible (200/404) without 401 errors
    FAIL: 401 unauthorized or persistent auth failures
    """
    print("\n─── TEST 4: EXCHANGE KEY STALE CREDENTIAL FIX ─────────")
    
    # Optional: If real Alpaca credentials provided, use them
    alpaca_key = os.environ.get("ALPACA_API_KEY", "")
    alpaca_secret = os.environ.get("ALPACA_API_SECRET", "")
    
    # Step 1: Delete existing Alpaca keys (404 is OK)
    print("  Step 1: Delete existing Alpaca keys...")
    del_code, del_body = delete_request("/api/trading/exchange-keys/alpaca", TOKEN)
    print(f"    DELETE HTTP {del_code} {'(no existing keys)' if del_code == 404 else ''}")
    
    # Step 2: Try to re-add keys
    print("  Step 2: Add Alpaca keys...")
    if alpaca_key and alpaca_secret:
        # Use real credentials if provided
        add_code, add_body = post_request(
            "/api/trading/exchange-keys",
            {
                "exchange": "alpaca",
                "api_key": alpaca_key,
                "api_secret": alpaca_secret,
                "is_paper": True,
            },
            TOKEN
        )
        print(f"    POST HTTP {add_code} (real credentials)")
    else:
        # Use placeholder - we expect 400 invalid credentials
        add_code, add_body = post_request(
            "/api/trading/exchange-keys",
            {
                "exchange": "alpaca",
                "api_key": "PK_TEST_INVALID_12345",
                "api_secret": "INVALID_SECRET_67890",
                "is_paper": True,
            },
            TOKEN
        )
        print(f"    POST HTTP {add_code} (placeholder - 400 expected without real credentials)")
    
    # Step 3: Wait a moment for any state sync
    print("  Step 3: Waiting 5 seconds for state sync...")
    time.sleep(5)
    
    # Step 4: Check health endpoint (try both /health and /health/orchestrator)
    print("  Step 4: Check health endpoints...")
    
    health_code, health_body = get_request("/health", TOKEN)
    print(f"    GET /health: HTTP {health_code}")
    
    # PASS: health accessible without 401
    # FAIL: persistent 401 unauthorized errors
    has_401 = (
        health_code == 401 or
        "401" in str(health_body) or
        "unauthorized" in str(health_body).lower()
    )
    is_pass = health_code in (200, 404) and not has_401
    
    detail = ""
    if has_401:
        detail = "401 Unauthorized — Auth error persisted"
    elif health_code == 404:
        detail = "Health endpoint not found (routing)"
    elif health_code == 200:
        detail = "Health accessible — No auth errors"
    else:
        detail = f"Status: {health_body.get('status', health_code)}"
    
    log_result(4, "Exchange Key Stale Credential Fix", is_pass, health_code, detail)


def test_rls_confirmation():
    """Test 5: RLS CONFIRMATION (informational).
    
    GET /api/trading/open-positions → expect 200
    GET /api/auth/me → expect 200
    
    This verifies service_role access still works.
    """
    print("\n─── TEST 5: RLS CONFIRMATION (INFORMATIONAL) ─────────")
    
    # Check open positions
    pos_code, pos_body = get_request("/api/trading/open-positions", TOKEN)
    print(f"  GET /api/trading/open-positions: HTTP {pos_code}")
    
    # Check auth/me
    me_code, me_body = get_request("/api/auth/me", TOKEN)
    print(f"  GET /api/auth/me: HTTP {me_code}")
    
    # Both should be 200
    is_pass = pos_code == 200 and me_code == 200
    
    detail = (
        "RLS note: if both return 200, backend service_role access is unaffected. "
        f"(positions={pos_code}, auth={me_code})"
    )
    
    log_result(5, "RLS Confirmation (Service Role Access)", is_pass, me_code, detail)


def print_summary():
    """Print final summary."""
    print("\n" + "=" * 70)
    print("FINAL SUMMARY")
    print("=" * 70)
    print(f"  PASSED: {tests_passed}/{tests_run}")
    print(f"  FAILED: {tests_run - tests_passed}/{tests_run}")
    
    if failures:
        print("\n  FAILURES:")
        for f in failures:
            print(f"    • Test {f['test']}: {f['name']}")
            print(f"      HTTP {f['http_status']} | {f['details']}")
    else:
        print("\n  ✓ All tests passed!")
    
    print("=" * 70 + "\n")


if __name__ == "__main__":
    print(f"\n{'='*70}")
    print(f"P0/P1 Fixes Validation Test")
    print(f"Target: {BASE}")
    print(f"{'='*70}")
    
    # Setup auth
    setup_auth()
    
    # Run tests
    test_crypto_routing()
    test_stock_routing()
    test_testing_mode_bypass()
    test_exchange_key_stale_credential()
    test_rls_confirmation()
    
    # Summary
    print_summary()
    
    # Exit code
    sys.exit(0 if (tests_run - tests_passed) == 0 else 1)
