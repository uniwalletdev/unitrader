"""
Direct trade test - bypasses signal analysis and executes a test trade
to Alpaca paper account to verify trading infrastructure works.
"""
import asyncio
import os
from alpaca_trade_api import REST

# Alpaca Paper credentials
API_KEY = os.getenv("ALPACA_PAPER_KEY", "your_key_here")
API_SECRET = os.getenv("ALPACA_PAPER_SECRET", "your_secret_here")
BASE_URL = "https://paper-api.alpaca.markets"

async def test_buy_aapl():
    """Execute a simple buy order for 1 share of AAPL."""
    try:
        api = REST(API_KEY, API_SECRET, BASE_URL)
        
        # Get account info
        account = api.get_account()
        print(f"Account status: {account.status}")
        print(f"Buying power: ${account.buying_power}")
        print(f"Cash: ${account.cash}")
        
        # Submit a simple buy order for 1 AAPL share
        order = api.submit_order(
            symbol="AAPL",
            qty=1,
            side="buy",
            type="market",
            time_in_force="day"
        )
        
        print(f"\n✅ Order submitted successfully!")
        print(f"Order ID: {order.id}")
        print(f"Symbol: {order.symbol}")
        print(f"Quantity: {order.qty}")
        print(f"Side: {order.side}")
        print(f"Status: {order.status}")
        
        return order
        
    except Exception as e:
        print(f"\n❌ Trade failed: {e}")
        return None

async def test_sell_aapl():
    """Execute a simple sell order for 1 share of AAPL."""
    try:
        api = REST(API_KEY, API_SECRET, BASE_URL)
        
        # Submit a simple sell order for 1 AAPL share
        order = api.submit_order(
            symbol="AAPL",
            qty=1,
            side="sell",
            type="market",
            time_in_force="day"
        )
        
        print(f"\n✅ Sell order submitted successfully!")
        print(f"Order ID: {order.id}")
        print(f"Symbol: {order.symbol}")
        print(f"Quantity: {order.qty}")
        print(f"Side: {order.side}")
        print(f"Status: {order.status}")
        
        return order
        
    except Exception as e:
        print(f"\n❌ Sell trade failed: {e}")
        return None

if __name__ == "__main__":
    print("=" * 60)
    print("ALPACA PAPER TRADING TEST")
    print("=" * 60)
    print(f"API Key configured: {'Yes' if API_KEY and API_KEY != 'your_key_here' else 'No'}")
    print(f"API Secret configured: {'Yes' if API_SECRET and API_SECRET != 'your_secret_here' else 'No'}")
    print("=" * 60)
    
    if API_KEY and API_KEY != "your_key_here":
        print("\n1. Testing BUY order for 1 AAPL share...")
        asyncio.run(test_buy_aapl())
        
        # Wait a moment
        print("\nWaiting 2 seconds...")
        import time
        time.sleep(2)
        
        print("\n2. Testing SELL order for 1 AAPL share...")
        asyncio.run(test_sell_aapl())
    else:
        print("\n⚠️  Alpaca credentials not configured in environment variables.")
        print("Set ALPACA_PAPER_KEY and ALPACA_PAPER_SECRET to test.")
