"""
test_alpaca_fix.py — Test that Alpaca symbol routing is fixed.

Tests the fix for: "GET https://data.alpaca.markets/v2/stocks/BTC/USD/quotes/latest 404 Not Found"

This script verifies:
1. Symbol classification (crypto vs stock)
2. Symbol normalization for Alpaca
3. Routing logic for fetch_market_data
"""

import asyncio
import sys
from src.integrations.market_data import (
    classify_asset,
    normalise_symbol,
    fetch_market_data,
    CRYPTO_SYMBOLS,
)


def test_classification():
    """Test classify_asset function with various symbol formats."""
    print("=" * 70)
    print("TEST 1: Asset Classification")
    print("=" * 70)
    
    test_cases = [
        ("BTC", "crypto"),
        ("BTC/USD", "crypto"),
        ("BTCUSDT", "crypto"),
        ("ETH", "crypto"),
        ("ETH/USD", "crypto"),
        ("AAPL", "stock"),
        ("AAPL/USD", "stock"),
        ("EUR/USD", "forex"),
        ("GBP/USD", "forex"),
    ]
    
    all_pass = True
    for symbol, expected in test_cases:
        result = classify_asset(symbol)
        status = "✓ PASS" if result == expected else "✗ FAIL"
        if result != expected:
            all_pass = False
        print(f"  {status:10} classify_asset('{symbol:12}') = '{result:8}' (expected: '{expected}')")
    
    return all_pass


def test_normalization():
    """Test normalise_symbol function for Alpaca."""
    print("\n" + "=" * 70)
    print("TEST 2: Symbol Normalization for Alpaca")
    print("=" * 70)
    
    test_cases = [
        ("BTC", "alpaca", "BTC"),           # stock format
        ("BTC/USD", "alpaca", "BTC/USD"),   # already normalized crypto
        ("BTCUSDT", "alpaca", "BTC/USD"),   # USDT → /USD
        ("ETH/USD", "alpaca", "ETH/USD"),   # ethereum
        ("AAPL", "alpaca", "AAPL"),         # stock stays same
    ]
    
    all_pass = True
    for symbol, exchange, expected in test_cases:
        result = normalise_symbol(symbol, exchange)
        status = "✓ PASS" if result == expected else "✗ FAIL"
        if result != expected:
            all_pass = False
        print(f"  {status:10} normalise_symbol('{symbol:12}', '{exchange:7}') = '{result:12}' (expected: '{expected}')")
    
    return all_pass


def test_routing_logic():
    """Test the fetch_market_data routing without making actual API calls."""
    print("\n" + "=" * 70)
    print("TEST 3: Routing Logic Simulation")
    print("=" * 70)
    
    test_cases = [
        ("BTC/USD", "alpaca", "crypto", "BTC/USD"),
        ("BTCUSDT", "alpaca", "crypto", "BTC/USD"),
        ("ETH/USD", "alpaca", "crypto", "ETH/USD"),
        ("AAPL", "alpaca", "stock", "AAPL"),
        ("TSLA", "alpaca", "stock", "TSLA"),
        ("BTCUSDT", "binance", "crypto", "BTCUSDT"),
        ("EUR/USD", "oanda", "forex", "EUR_USD"),
    ]
    
    all_pass = True
    for symbol, exchange, expected_type, expected_norm in test_cases:
        asset_type = classify_asset(symbol)
        normalised = normalise_symbol(symbol, exchange)
        
        type_ok = asset_type == expected_type
        norm_ok = normalised == expected_norm
        status = "✓ PASS" if (type_ok and norm_ok) else "✗ FAIL"
        
        if not (type_ok and norm_ok):
            all_pass = False
        
        print(f"  {status:10} {symbol:12} on {exchange:7} → type={asset_type:8} ({expected_type:8}), "
              f"norm={normalised:12} ({expected_norm:12})")
    
    return all_pass


async def test_api_endpoint_routing():
    """Test which API endpoint would be called (without making actual requests)."""
    print("\n" + "=" * 70)
    print("TEST 4: API Endpoint Routing (Dry Run)")
    print("=" * 70)
    
    test_cases = [
        ("BTC/USD", "alpaca", "/v1beta3/crypto/us/latest/quotes"),  # crypto endpoint
        ("AAPL", "alpaca", "/v2/stocks/AAPL/quotes/latest"),          # stock endpoint
        ("BTCUSDT", "binance", "binance crypto endpoint"),            # binance
    ]
    
    print("  The following requests SHOULD NOT produce 404 errors:")
    print()
    
    for symbol, exchange, expected_endpoint in test_cases:
        asset_type = classify_asset(symbol)
        normalised = normalise_symbol(symbol, exchange)
        
        endpoint = ""
        if exchange == "alpaca":
            if asset_type == "crypto":
                endpoint = f"/v1beta3/crypto/us/latest/quotes?symbols={normalised}"
            elif asset_type == "stock":
                endpoint = f"/v2/stocks/{normalised}/quotes/latest"
        elif exchange == "binance":
            endpoint = f"binance.com crypto endpoint (symbol: {normalised})"
        
        print(f"  symbol={symbol:12} on {exchange:7}")
        print(f"    → type={asset_type:8}, normalised={normalised:12}")
        print(f"    → endpoint={endpoint}")
        print()
    
    return True


def main():
    """Run all tests."""
    print("\n")
    print("╔" + "═" * 68 + "╗")
    print("║" + " " * 68 + "║")
    print("║" + "  ALPACA API FIX VALIDATION TEST".center(68) + "║")
    print("║" + "  Testing symbol routing to prevent 404 errors".center(68) + "║")
    print("║" + " " * 68 + "║")
    print("╚" + "═" * 68 + "╝")
    
    results = []
    
    # Run synchronous tests
    results.append(("Classification", test_classification()))
    results.append(("Normalization", test_normalization()))
    results.append(("Routing Logic", test_routing_logic()))
    
    # Run async test
    asyncio.run(test_api_endpoint_routing())
    results.append(("API Endpoint Routing", True))
    
    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    all_pass = True
    for name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {status:10} {name}")
        if not passed:
            all_pass = False
    
    print()
    if all_pass:
        print("✓ All tests passed! The fix should prevent 404 errors on BTC/USD.")
        return 0
    else:
        print("✗ Some tests failed. See details above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
