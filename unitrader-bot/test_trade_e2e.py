"""
End-to-end trade test for olayinkafalokun360@gmail.com on Alpaca paper trading.

Steps:
  1. Check backend health
  2. Login as the test user
  3. Verify exchange keys exist for Alpaca
  4. Execute a BTC paper trade on Alpaca
  5. Print full result
"""

import asyncio
import sys
import os
import json
import logging

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("test_trade_e2e")

TARGET_EMAIL = "olayinkafalokun360@gmail.com"


async def main():
    # ── Import project internals ──────────────────────────────────────────
    from config import settings
    from database import AsyncSessionLocal, create_tables
    from models import User, ExchangeAPIKey, UserSettings, TradingAccount, Trade
    from sqlalchemy import select, func

    print("=" * 70)
    print("  UNITRADER — End-to-End Trade Test")
    print("=" * 70)

    # ── Step 0: Config sanity ─────────────────────────────────────────────
    print("\n[0] Config check:")
    print(f"    ANTHROPIC_API_KEY set:      {bool(settings.anthropic_api_key)}")
    print(f"    ALPACA_PAPER_API_KEY set:   {bool(settings.alpaca_paper_api_key)}")
    print(f"    ALPACA_PAPER_API_SECRET set:{bool(settings.alpaca_paper_api_secret)}")
    print(f"    ALPACA_PAPER_BASE_URL:      {settings.alpaca_paper_base_url}")
    print(f"    ALPACA_DATA_URL:            {getattr(settings, 'alpaca_data_url', 'N/A')}")
    print(f"    TESTING_MODE:               {settings.testing_mode}")
    print(f"    DATABASE_URL prefix:        {str(settings.database_url)[:40]}...")

    if not settings.anthropic_api_key:
        print("\n❌ ANTHROPIC_API_KEY is missing — Claude cannot make trade decisions.")
        return
    if not settings.alpaca_paper_api_key:
        print("\n❌ ALPACA_PAPER_API_KEY is missing — cannot trade on Alpaca.")
        return

    # ── Step 1: DB + Find user ────────────────────────────────────────────
    await create_tables()
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.email == TARGET_EMAIL))
        user = result.scalar_one_or_none()

        if not user:
            print(f"\n❌ User {TARGET_EMAIL} not found in database.")
            return

        print(f"\n[1] User found:")
        print(f"    ID:                  {user.id}")
        print(f"    Email:               {user.email}")
        print(f"    Active:              {user.is_active}")
        print(f"    AI Name:             {getattr(user, 'ai_name', 'N/A')}")
        print(f"    Subscription tier:   {getattr(user, 'subscription_tier', 'N/A')}")
        print(f"    Stripe sub status:   {getattr(user, 'stripe_subscription_status', 'N/A')}")
        print(f"    Trial status:        {getattr(user, 'trial_status', 'N/A')}")
        print(f"    Trial end:           {getattr(user, 'trial_end_date', 'N/A')}")

        # ── Step 2: Check trade limit ─────────────────────────────────────
        print(f"\n[2] Trade limit check:")
        from src.services.subscription import check_trade_limit
        trade_check = await check_trade_limit(user, db)
        print(f"    Allowed:    {trade_check['allowed']}")
        print(f"    Used:       {trade_check.get('trades_used', '?')}")
        print(f"    Limit:      {trade_check.get('trades_limit', 'unlimited')}")
        if not trade_check["allowed"]:
            print(f"    Reason:     {trade_check.get('reason', '?')}")
            print(f"\n⚠️  Trade limit blocks execution. Set TESTING_MODE=true in .env to bypass.")
            if settings.testing_mode.lower() != "true":
                return

        # ── Step 3: Check exchange keys ───────────────────────────────────
        print(f"\n[3] Exchange keys (Alpaca):")
        key_result = await db.execute(
            select(ExchangeAPIKey).where(
                ExchangeAPIKey.user_id == user.id,
                ExchangeAPIKey.exchange == "alpaca",
            )
        )
        keys = key_result.scalars().all()
        if not keys:
            print("    ❌ No Alpaca API keys found for this user in ExchangeAPIKey table.")
            print("    → The user needs to connect Alpaca via the frontend (Settings > Exchanges)")
            print("    → Or keys need to be inserted into the database.")
            return
        for k in keys:
            print(f"    Key ID:      {k.id}")
            print(f"    Exchange:    {k.exchange}")
            print(f"    Active:      {k.is_active}")
            print(f"    Paper:       {getattr(k, 'is_paper', 'N/A')}")
            print(f"    Account ID:  {getattr(k, 'trading_account_id', 'N/A')}")
            print(f"    Created:     {getattr(k, 'created_at', 'N/A')}")

        active_key = next((k for k in keys if k.is_active), None)
        if not active_key:
            print("    ❌ No ACTIVE Alpaca key found. All keys are deactivated.")
            return

        # ── Step 3b: Check trading accounts ───────────────────────────────
        print(f"\n[3b] Trading accounts (Alpaca):")
        acct_result = await db.execute(
            select(TradingAccount).where(
                TradingAccount.user_id == user.id,
                TradingAccount.exchange == "alpaca",
            )
        )
        accounts = acct_result.scalars().all()
        if not accounts:
            print("    No TradingAccount rows — run_cycle will still work via ExchangeAPIKey fallback.")
        for a in accounts:
            print(f"    Account ID:  {a.id}")
            print(f"    Paper:       {a.is_paper}")
            print(f"    Active:      {a.is_active}")
            print(f"    Label:       {getattr(a, 'label', 'N/A')}")

        # ── Step 4: Test Alpaca connectivity ──────────────────────────────
        print(f"\n[4] Testing Alpaca paper API connectivity...")
        from security import decrypt_api_key
        from src.integrations.exchange_client import get_exchange_client

        try:
            raw_key, raw_secret = decrypt_api_key(
                active_key.encrypted_api_key,
                active_key.encrypted_api_secret,
            )
            is_paper = getattr(active_key, "is_paper", True)
            client = get_exchange_client("alpaca", raw_key, raw_secret, is_paper=is_paper)
            raw_key = raw_secret = None

            balance = await client.get_account_balance()
            print(f"    ✅ Alpaca connected! Balance: ${balance:,.2f}")
            await client.aclose()
        except Exception as exc:
            print(f"    ❌ Alpaca connection failed: {exc}")
            print(f"    → Check the stored API keys are valid for Alpaca paper trading")
            return

        # ── Step 5: Test market data fetch ────────────────────────────────
        print(f"\n[5] Fetching market data for BTC/USD on Alpaca...")
        from src.integrations.market_data import full_market_analysis

        try:
            market = await full_market_analysis("BTC/USD", "alpaca")
            print(f"    ✅ Market data received:")
            print(f"       Price:      ${market.get('price', 0):,.2f}")
            print(f"       Trend:      {market.get('trend', 'unknown')}")
            print(f"       RSI:        {market.get('indicators', {}).get('rsi', 'N/A')}")
        except Exception as exc:
            print(f"    ❌ Market data fetch failed: {exc}")
            print(f"    → This will cause run_cycle to abort.")
            return

        # ── Step 6: User settings ─────────────────────────────────────────
        print(f"\n[6] User settings:")
        settings_result = await db.execute(
            select(UserSettings).where(UserSettings.user_id == user.id)
        )
        user_settings = settings_result.scalar_one_or_none()
        if user_settings:
            print(f"    Max position size:  {user_settings.max_position_size}%")
            print(f"    Max daily loss:     {user_settings.max_daily_loss}%")
            print(f"    Onboarding done:    {getattr(user_settings, 'onboarding_complete', 'N/A')}")
            print(f"    Approved assets:    {getattr(user_settings, 'approved_assets', 'N/A')}")
        else:
            print("    No UserSettings row — defaults will be used.")

    # ── Step 7: EXECUTE THE TRADE ─────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print(f"  [7] EXECUTING TRADE: BTC on Alpaca (paper)")
    print(f"{'=' * 70}")

    from src.agents.core.trading_agent import TradingAgent

    agent = TradingAgent(user_id=user.id)
    try:
        result = await agent.run_cycle(
            symbol="BTC",
            exchange_name="alpaca",
            is_paper=True,
        )
        print(f"\n  ✅ run_cycle completed!")
        print(f"  Result:")
        print(json.dumps(result, indent=4, default=str))

        if isinstance(result, dict):
            status = result.get("status")
            if status == "executed":
                print(f"\n  🎉 TRADE EXECUTED SUCCESSFULLY!")
                print(f"     Symbol:     {result.get('symbol')}")
                print(f"     Side:       {result.get('decision') or result.get('side')}")
                print(f"     Entry:      ${result.get('entry_price', 0):,.4f}")
                print(f"     Stop Loss:  ${result.get('stop_loss', 0):,.4f}")
                print(f"     Take Profit:${result.get('take_profit', 0):,.4f}")
                print(f"     Quantity:   {result.get('quantity')}")
                print(f"     Confidence: {result.get('confidence')}%")
                print(f"     Trade ID:   {result.get('trade_id')}")
                print(f"\n  → Check your Alpaca paper dashboard to see the order!")
            elif status == "wait":
                print(f"\n  ⏳ Claude decided to WAIT (no trade placed)")
                print(f"     Confidence: {result.get('confidence')}%")
                print(f"     Reason:     {result.get('reasoning', 'N/A')}")
            elif status == "rejected":
                print(f"\n  ❌ Trade REJECTED")
                print(f"     Reason:     {result.get('reason', 'N/A')}")
            elif status == "skipped":
                print(f"\n  ⏭️ Trade SKIPPED")
                print(f"     Reason:     {result.get('reason', 'N/A')}")
            elif status == "error":
                print(f"\n  ❌ Trade ERROR")
                print(f"     Reason:     {result.get('reason', 'N/A')}")
            else:
                print(f"\n  ❓ Unknown status: {status}")
    except Exception as exc:
        logger.exception("run_cycle raised an exception")
        print(f"\n  ❌ EXCEPTION during trade execution: {exc}")


if __name__ == "__main__":
    asyncio.run(main())
