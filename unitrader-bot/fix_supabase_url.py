#!/usr/bin/env python3
"""
Supabase DATABASE_URL checker and fixer.
Run: python fix_supabase_url.py
Paste your current DATABASE_URL when prompted.
"""
import sys
import urllib.parse


def check_and_fix(url: str) -> str:
    url = url.strip().strip('"').strip("'")

    print(f"\nOriginal URL: {url[:80]}...")

    # ── Detect URL type ──────────────────────────────────────────────
    if "pooler.supabase.com" in url:
        if ":6543" in url:
            print("  URL type: Transaction Pooler (port 6543)  ← CORRECT")
            pooler_ok = True
        elif ":5432" in url:
            print("  URL type: Session Pooler or Direct (port 5432)  ← may fail on Railway")
            pooler_ok = False
        else:
            print("  URL type: Unknown port")
            pooler_ok = False
    elif "db." in url and "supabase.co" in url:
        print("  URL type: Direct connection (db.xxx.supabase.co)  ← will FAIL on Railway (no direct access)")
        pooler_ok = False
    else:
        print("  URL type: Could not detect Supabase URL pattern")
        pooler_ok = False

    # ── Parse ────────────────────────────────────────────────────────
    try:
        parsed = urllib.parse.urlparse(url)
        scheme   = parsed.scheme
        username = parsed.username
        password = parsed.password
        host     = parsed.hostname
        port     = parsed.port
        dbname   = parsed.path.lstrip("/")
        params   = dict(urllib.parse.parse_qsl(parsed.query))
    except Exception as e:
        print(f"  Could not parse URL: {e}")
        return url

    print(f"  Host:     {host}")
    print(f"  Port:     {port}")
    print(f"  User:     {username}")
    print(f"  Database: {dbname}")
    print(f"  Params:   {params}")

    # ── Password encoding ────────────────────────────────────────────
    if password:
        encoded_pw = urllib.parse.quote(password, safe="")
        if encoded_pw != password:
            print(f"  Password has special chars — encoding: {password[:3]}... → {encoded_pw[:3]}...")
        else:
            print(f"  Password: OK (no special chars)")
    else:
        print("  WARNING: No password found in URL")

    # ── Build fixed URL ──────────────────────────────────────────────
    # Force: postgresql+asyncpg, port 6543 (pooler), encode password, no sslmode in URL
    # (SSL is handled by SQLAlchemy connect_args)
    fixed_port  = 6543
    fixed_host  = host

    # If they gave the direct connection host, swap to pooler
    if host and host.startswith("db.") and "supabase.co" in host:
        project_ref = host.split(".")[1]
        fixed_host = f"aws-0-us-east-1.pooler.supabase.com"
        print(f"\n  FIXING: Direct host → Pooler host")
        print(f"  NOTE:   Check your Supabase Settings > Database > Connection pooling")
        print(f"          for the correct pooler region (us-east-1, eu-west-1, etc.)")

    encoded_pw = urllib.parse.quote(password or "", safe="")
    fixed_url = (
        f"postgresql+asyncpg://{username}:{encoded_pw}@{fixed_host}:{fixed_port}/{dbname}"
    )

    print(f"\n  Fixed URL (paste into Railway):")
    print(f"\n  DATABASE_URL={fixed_url}\n")

    return fixed_url


def main():
    print("=" * 60)
    print("  Supabase DATABASE_URL Fixer for Unitrader / Railway")
    print("=" * 60)
    print()
    print("Where to find your URL:")
    print("  Supabase Dashboard → Settings → Database → Connection string")
    print("  Click 'URI' tab → choose 'Transaction pooler' (port 6543)")
    print("  Replace [YOUR-PASSWORD] with your actual DB password")
    print()

    if len(sys.argv) > 1:
        url = " ".join(sys.argv[1:])
    else:
        url = input("Paste your DATABASE_URL here: ").strip()

    if not url:
        print("No URL provided.")
        return

    fixed = check_and_fix(url)

    print("\n" + "=" * 60)
    print("NEXT STEPS:")
    print("  1. Copy the 'Fixed URL' above")
    print("  2. Go to Railway → your backend service → Variables")
    print("  3. Update DATABASE_URL to the fixed URL")
    print("  4. Railway will auto-redeploy (~30 seconds)")
    print("  5. Run: python test_production.py")
    print("=" * 60)


if __name__ == "__main__":
    main()
