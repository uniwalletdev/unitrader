"""Delete a user by email from the Unitrader database."""
import asyncio
import sys
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import select, delete
from sqlalchemy.pool import NullPool
from config import settings
from models import User

async def delete_user(email: str, use_production: bool = False):
    # Create engine
    if use_production:
        db_url = settings.supabase_service_key
        # Use NullPool for Supabase transaction pooler
        engine = create_async_engine(db_url, echo=False, poolclass=NullPool)
    else:
        db_url = settings.database_url
        if db_url.startswith("postgresql://"):
            db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        elif db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)
        engine = create_async_engine(db_url, echo=False)

    async with AsyncSession(engine) as session:
        # Find the user
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if not user:
            print(f"User with email {email} not found.")
            return

        print(f"Found user ID: {user.id}")

        # Delete the user (cascade will handle related records)
        await session.execute(delete(User).where(User.id == user.id))
        await session.commit()

        print(f"Successfully deleted user {email}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python delete_user.py <email> [--production]")
        sys.exit(1)

    email = sys.argv[1]
    use_production = "--production" in sys.argv
    asyncio.run(delete_user(email, use_production))