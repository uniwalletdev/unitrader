"""Test the trial endpoints using a valid JWT token."""
import asyncio, sys, httpx
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

async def test():
    from database import AsyncSessionLocal
    from sqlalchemy import select
    from models import User
    from security import create_access_token

    # Get first user from DB and create a token for them directly
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).limit(1))
        user = result.scalar_one_or_none()
        if not user:
            print("No users in DB")
            return
        print(f"Testing as user: {user.email} | ai_name={user.ai_name} | trial_status={user.trial_status}")

    token = create_access_token(str(user.id))
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=30.0) as c:
        # ── Trial Status ─────────────────────────────────────────────
        r = await c.get("/api/trial/status", headers=headers)
        print(f"\nGET /api/trial/status → {r.status_code}")
        if r.status_code == 200:
            d = r.json()
            print(f"  status:           {d['status']}")
            print(f"  phase:            {d['phase']}")
            print(f"  days_remaining:   {d['days_remaining']}")
            print(f"  banner:           {d['banner'][:70]}")
            print(f"  show_modal:       {d['show_choice_modal']}")
            print(f"  trades_made:      {d['performance']['trades_made']}")
            print(f"  net_pnl:          {d['performance']['net_pnl']}")
            print(f"  summary:          {d['performance_summary'][:70]}")
        else:
            print(f"  ERROR: {r.text}")

        # ── Choice Options ───────────────────────────────────────────
        r2 = await c.get("/api/trial/choice-options", headers=headers)
        print(f"\nGET /api/trial/choice-options → {r2.status_code}")
        if r2.status_code == 200:
            d2 = r2.json()
            for opt in d2["options"]:
                print(f"  [{opt['choice']}] {opt['label']} — {opt.get('price','N/A')}")
        else:
            print(f"  ERROR: {r2.text}")

        # ── Make Choice: free ────────────────────────────────────────
        r3 = await c.post("/api/trial/make-choice", json={"choice": "free"}, headers=headers)
        print(f"\nPOST /api/trial/make-choice (free) → {r3.status_code}")
        if r3.status_code == 200:
            d3 = r3.json()
            print(f"  result:   {d3['status']}")
            print(f"  message:  {d3['message'][:70]}")
            print("\nPASS - all trial endpoints working!")
        else:
            print(f"  ERROR: {r3.text}")

asyncio.run(test())
