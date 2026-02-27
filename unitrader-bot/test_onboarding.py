"""Quick test for clerk-setup fix."""
import asyncio, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

async def test():
    import httpx
    from database import AsyncSessionLocal
    from sqlalchemy import select
    from models import User

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).limit(1))
        user = result.scalar_one_or_none()
        if not user:
            print("No users in DB yet.")
            return
        print(f"Testing clerk-setup for user: {user.email} (id={user.id})")

        # Reset ai_name to simulate first-time onboarding
        original_name = user.ai_name
        user.ai_name = ""
        await db.commit()

    async with httpx.AsyncClient(base_url="http://localhost:8000") as c:
        r = await c.post("/api/auth/clerk-setup", json={
            "user_id": str(user.id),
            "ai_name": "AlphaBot9"
        })
        print(f"Status: {r.status_code}")
        data = r.json()
        if r.status_code == 200:
            tok = data.get("access_token", "")
            ref = data.get("refresh_token", "")
            uid = data.get("user", {}).get("id", "")
            print(f"  access_token  -> type={type(tok).__name__}, value={str(tok)[:40]}...")
            print(f"  refresh_token -> type={type(ref).__name__}, value={str(ref)[:40]}...")
            print(f"  user.id       -> type={type(uid).__name__}, value={uid}")
            if isinstance(tok, str) and isinstance(ref, str):
                print("PASS - tokens are proper strings, onboarding works!")
            else:
                print("FAIL - tokens are not strings (old tuple bug still present)")
        else:
            print(f"FAIL: {data}")

    # Restore original name
    async with AsyncSessionLocal() as db2:
        result2 = await db2.execute(select(User).where(User.id == user.id))
        u2 = result2.scalar_one()
        u2.ai_name = original_name or "AlphaBot9"
        await db2.commit()
        print(f"Restored ai_name to: {u2.ai_name}")

asyncio.run(test())
