#!/usr/bin/env python3
"""Debug script to check exchange API key status for a user."""

import asyncio
import sys
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# Adjust import based on your project structure
from models import ExchangeAPIKey, TradingAccount, User
from config import settings

async def check_exchange_keys(user_email: str):
    """Check exchange API key status for a specific user."""
    
    # Translate sync postgres:// → async asyncpg driver notation
    db_url = settings.database_url
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)
    
    engine = create_async_engine(db_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        try:
            # Find user by email
            result = await session.execute(
                select(User).where(User.email == user_email)
            )
            user = result.scalar_one_or_none()
            
            if not user:
                print(f"❌ User not found: {user_email}")
                return
            
            print(f"✓ User found: {user.username} ({user.email})")
            print(f"  AI Name: {user.ai_name}")
            print()
            
            # Check exchange API keys
            result = await session.execute(
                select(ExchangeAPIKey)
                .where(ExchangeAPIKey.user_id == user.id)
            )
            keys = result.scalars().all()
            
            if not keys:
                print("❌ No exchange API keys found for this user")
                return
            
            print(f"Found {len(keys)} exchange API key(s):\n")
            
            for key in keys:
                print(f"  Exchange: {key.exchange}")
                print(f"    ID: {key.id}")
                print(f"    Active: {'✓ YES' if key.is_active else '❌ NO (DISABLED)'}")
                print(f"    Paper trading: {key.is_paper}")
                print(f"    Created: {key.created_at}")
                
                # Check associated trading account
                if key.trading_account_id:
                    result = await session.execute(
                        select(TradingAccount).where(
                            TradingAccount.id == key.trading_account_id
                        )
                    )
                    account = result.scalar_one_or_none()
                    if account:
                        print(f"    Trading Account: {account.account_name}")
                        print(f"    Last balance: ${account.last_known_balance_usd}")
                        print(f"    Last synced: {account.last_synced_at}")
                print()
            
            # Summary
            active_keys = [k for k in keys if k.is_active]
            print(f"\n📊 Summary:")
            print(f"  Total keys: {len(keys)}")
            print(f"  Active keys: {len(active_keys)}")
            
            if len(active_keys) == 0:
                print("\n⚠️  WARNING: No active exchange keys!")
                print("   This is why the chat shows 'Connect an exchange'")
                print("\n   To fix: Update ExchangeAPIKey.is_active = True for one or more keys")
        
        finally:
            await engine.dispose()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python debug_exchange_keys.py <user_email>")
        print("\nExample: python debug_exchange_keys.py user@example.com")
        sys.exit(1)
    
    user_email = sys.argv[1]
    asyncio.run(check_exchange_keys(user_email))
