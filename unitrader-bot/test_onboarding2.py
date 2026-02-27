"""Direct function test to get the real traceback."""
import asyncio, sys, traceback
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

async def test():
    from database import AsyncSessionLocal
    from sqlalchemy import select
    from models import User, UserSettings, RefreshToken
    from security import create_access_token, create_refresh_token, validate_ai_name
    import uuid

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).limit(1))
        user = result.scalar_one_or_none()
        if not user:
            print("No users in DB")
            return

        print(f"User: {user.email}, id={user.id}, type={type(user.id)}")

        # Simulate exactly what clerk_setup does
        ai_name = "TestAlpha"
        print(f"\n--- Testing validate_ai_name ---")
        valid = validate_ai_name(ai_name)
        print(f"validate_ai_name('{ai_name}') = {valid}")

        print(f"\n--- Testing create_refresh_token ---")
        result_rt = create_refresh_token(str(user.id))
        print(f"create_refresh_token returned: type={type(result_rt)}, value={repr(result_rt)[:80]}")

        if isinstance(result_rt, tuple):
            refresh_token_str, refresh_expires = result_rt
            print(f"  token (str): {refresh_token_str[:40]}...")
            print(f"  expires_at: {refresh_expires}")
        else:
            refresh_token_str = result_rt
            print(f"  WARN: not a tuple, value: {refresh_token_str}")

        print(f"\n--- Testing RefreshToken model ---")
        rt = RefreshToken(
            token=refresh_token_str,
            user_id=user.id,
            expires_at=refresh_expires,
        )
        print(f"  RefreshToken fields: token={type(rt.token)}, user_id={type(rt.user_id)}, expires_at={type(rt.expires_at)}")

        print(f"\n--- Testing DB insert ---")
        try:
            async with AsyncSessionLocal() as db2:
                # Check AI name not taken
                taken = await db2.execute(
                    select(User).where(User.ai_name == ai_name + "_unique_test_999")
                )
                print("  DB select OK")
                
                # Test user lookup by string ID
                uid_str = str(user.id)
                result2 = await db2.execute(select(User).where(User.id == uid_str))
                u2 = result2.scalar_one_or_none()
                print(f"  User lookup by string id: {'FOUND' if u2 else 'NOT FOUND'}")
        except Exception as e:
            print(f"  DB ERROR: {e}")
            traceback.print_exc()

asyncio.run(test())
