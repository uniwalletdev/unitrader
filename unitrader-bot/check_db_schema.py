"""Quick check of SQLite schema vs ORM expectations."""
import sqlite3

conn = sqlite3.connect("unitrader.db")
c = conn.cursor()

# Tables
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in c.fetchall()]
print("Tables:", tables)

# Users columns
c.execute("PRAGMA table_info(users)")
user_cols = [row[1] for row in c.fetchall()]
print("\nusers cols:", user_cols)

# exchange_api_keys
if "exchange_api_keys" in tables:
    c.execute("PRAGMA table_info(exchange_api_keys)")
    print("\nexchange_api_keys cols:", [row[1] for row in c.fetchall()])
else:
    print("\nexchange_api_keys table: MISSING")

# trading_accounts
if "trading_accounts" in tables:
    c.execute("PRAGMA table_info(trading_accounts)")
    print("\ntrading_accounts cols:", [row[1] for row in c.fetchall()])
else:
    print("\ntrading_accounts table: MISSING")

# trades
if "trades" in tables:
    c.execute("PRAGMA table_info(trades)")
    print("\ntrades cols:", [row[1] for row in c.fetchall()])
else:
    print("\ntrades table: MISSING")

# user_settings
if "user_settings" in tables:
    c.execute("PRAGMA table_info(user_settings)")
    print("\nuser_settings cols:", [row[1] for row in c.fetchall()])
else:
    print("\nuser_settings table: MISSING")

# Check user
c.execute("SELECT id, email, is_active, subscription_tier, trial_status FROM users WHERE email='olayinkafalokun360@gmail.com'")
row = c.fetchone()
print("\nTarget user:", row)

# Count exchange keys for user
if row and "exchange_api_keys" in tables:
    c.execute("SELECT id, exchange, is_active FROM exchange_api_keys WHERE user_id=?", (row[0],))
    keys = c.fetchall()
    print("User exchange keys:", keys)

conn.close()
