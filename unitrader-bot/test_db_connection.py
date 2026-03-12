#!/usr/bin/env python3
"""
Direct Supabase connection test - run this LOCALLY to verify DB works
before deploying to Railway.

Usage:
    python test_db_connection.py
"""
import asyncio
import sys
import urllib.parse

# ── Your Supabase URL (hardcoded for quick test) ───────────────────────────
# Using Transaction Pooler (port 6543) with URL-encoded password
SUPABASE_URL = (
    "postgresql+asyncpg://"
    "postgres.msrmjcvtsxhsxbfpefgo"
    ":Godson63295178%21"
    "@aws-1-eu-central-1.pooler.supabase.com"
    ":5432/postgres"  # Session Pooler (session mode — supports prepared statements)
)


async def test_connection(url: str) -> bool:
    try:
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy import text
    except ImportError:
        print("  Installing sqlalchemy...")
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "sqlalchemy[asyncio]", "asyncpg"], check=True)
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy import text

    # Try 1: with ssl=True
    print(f"\nAttempt 1: ssl=True (asyncpg style)")
    try:
        engine = create_async_engine(url, connect_args={"ssl": True}, pool_pre_ping=True)
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT version()"))
            row = result.fetchone()
            print(f"  [PASS] Connected! PostgreSQL version: {str(row[0])[:60]}")
        await engine.dispose()
        print(f"\n  Use this in Railway DATABASE_URL:")
        print(f"  {url}")
        return True
    except Exception as e:
        print(f"  [FAIL] {e}")

    # Try 2: without ssl connect_args, add ?sslmode=require to URL
    url2 = url + "?sslmode=require" if "?" not in url else url + "&sslmode=require"
    print(f"\nAttempt 2: sslmode=require in URL")
    try:
        engine = create_async_engine(url2, pool_pre_ping=True)
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT version()"))
            row = result.fetchone()
            print(f"  [PASS] Connected! PostgreSQL version: {str(row[0])[:60]}")
        await engine.dispose()
        print(f"\n  Use this in Railway DATABASE_URL:")
        print(f"  {url2}")
        return True
    except Exception as e:
        print(f"  [FAIL] {e}")

    # Try 3: no SSL at all
    print(f"\nAttempt 3: No SSL")
    try:
        engine = create_async_engine(url, pool_pre_ping=True)
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT version()"))
            row = result.fetchone()
            print(f"  [PASS] Connected! PostgreSQL version: {str(row[0])[:60]}")
        await engine.dispose()
        print(f"\n  Use this in Railway DATABASE_URL:")
        print(f"  {url}")
        return True
    except Exception as e:
        print(f"  [FAIL] {e}")

    # Try 4: statement_cache_size=0 (required for Supabase Transaction Pooler / PgBouncer)
    print(f"\nAttempt 4: statement_cache_size=0 (PgBouncer fix)")
    try:
        engine = create_async_engine(url, connect_args={"statement_cache_size": 0}, pool_pre_ping=True)
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT version()"))
            row = result.fetchone()
            print(f"  [PASS] Connected! PostgreSQL version: {str(row[0])[:60]}")
        await engine.dispose()
        print(f"\n  Use this in Railway DATABASE_URL:")
        print(f"  {url}")
        return True
    except Exception as e:
        print(f"  [FAIL] {e}")

    return False


def main():
    print("=" * 60)
    print("  Direct Supabase Connection Test")
    print("=" * 60)
    print(f"\nTesting: {SUPABASE_URL[:70]}...")

    ok = asyncio.run(test_connection(SUPABASE_URL))

    print()
    if ok:
        print("SUCCESS — copy the working URL above into Railway → Variables → DATABASE_URL")
        print("Then commit and push config.py (the ssl fix) to redeploy Railway.")
    else:
        print("ALL ATTEMPTS FAILED. Check:")
        print("  1. Is your Supabase project active? (not paused)")
        print("  2. Visit: https://supabase.com/dashboard/project/msrmjcvtsxhsxbfpefgo")
        print("  3. If paused, click 'Restore project'")
        print("  4. Is your password correct? Try resetting it in Settings > Database")
    print("=" * 60)


if __name__ == "__main__":
    main()
