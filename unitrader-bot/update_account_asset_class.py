"""Update trading account asset_class to enable crypto for Alpaca."""
import sqlite3
import sys

conn = sqlite3.connect("unitrader.db")
c = conn.cursor()

# Check current trading accounts
print("Current trading accounts:")
c.execute("SELECT id, user_id, exchange, asset_class, is_active FROM trading_accounts")
rows = c.fetchall()
for row in rows:
    print(f"  ID: {row[0]}, User: {row[1]}, Exchange: {row[2]}, Asset Class: {row[3]}, Active: {row[4]}")

# Update Alpaca accounts to enable crypto (note: this is a workaround)
# The proper fix is in the backend (market_context.py) which should return both classes
# But if the DB has old data, this can help
c.execute("""
    UPDATE trading_accounts 
    SET asset_class = 'crypto' 
    WHERE exchange = 'alpaca' AND asset_class = 'stocks'
""")
updated = c.rowcount
print(f"\nUpdated {updated} Alpaca accounts to asset_class='crypto'")

conn.commit()
conn.close()
print("\nDone. Note: The backend fix in market_context.py should handle this automatically.")
