"""
Update Alpaca API key in database directly.
Run this to fix the 401 Unauthorized error.
"""
import asyncio
import os
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from database import engine, get_db
from models import ExchangeAPIKey
from security import encrypt_api_key

# Your new Alpaca credentials - UPDATE THESE
ALPACA_KEY = "PKUJGXY23T4WP3FGGLKM3RNETF"  # Your paper key
ALPACA_SECRET = "BTA8N3MKAorN4x1keK5myRs8TxW9ksT9WtX92ErBbuwX"  # Your paper secret

async def update_alpaca_key():
    """Update Alpaca API key for user in database."""
    async with engine.begin() as conn:
        # Find the Alpaca key for the user
        result = await conn.execute(
            select(ExchangeAPIKey).where(
                ExchangeAPIKey.exchange == "alpaca"
            )
        )
        keys = result.scalars().all()
        
        if not keys:
            print("❌ No Alpaca keys found in database")
            return
        
        print(f"Found {len(keys)} Alpaca key(s):")
        for key in keys:
            print(f"  - ID: {key.id}, User: {key.user_id}, Active: {key.is_active}")
        
        # Encrypt the new credentials
        encrypted_key, encrypted_secret = encrypt_api_key(ALPACA_KEY, ALPACA_SECRET)
        
        # Update all Alpaca keys (usually there's just one per user)
        for key in keys:
            await conn.execute(
                update(ExchangeAPIKey)
                .where(ExchangeAPIKey.id == key.id)
                .values(
                    encrypted_api_key=encrypted_key,
                    encrypted_api_secret=encrypted_secret,
                    is_active=True,
                    updated_at=datetime.utcnow()
                )
            )
            print(f"✅ Updated key {key.id}")
        
        await conn.commit()
        print("\n✅ Alpaca API keys updated successfully!")
        print("The 401 error should be resolved.")

if __name__ == "__main__":
    from datetime import datetime
    print("=" * 60)
    print("UPDATE ALPACA API KEY IN DATABASE")
    print("=" * 60)
    print(f"Key: {ALPACA_KEY[:10]}...")
    print(f"Secret: {ALPACA_SECRET[:10]}...")
    print("=" * 60)
    
    asyncio.run(update_alpaca_key())
