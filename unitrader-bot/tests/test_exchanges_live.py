"""
tests/test_exchanges_live.py — Live integration tests for all exchange connectors.

Tests real API connections to Binance (testnet), Alpaca (paper), and OANDA (practice).
All tests are marked `live` and `exchange` — they are skipped automatically if
the required API keys are missing from the environment.

═══════════════════════════════════════════════════════════
SETUP INSTRUCTIONS
═══════════════════════════════════════════════════════════

BINANCE (testnet — no real money):
  1. Visit: https://testnet.binance.vision
  2. Generate API key + secret
  3. Add to .env.test:
       BINANCE_API_KEY=your_testnet_key
       BINANCE_API_SECRET=your_testnet_secret
       BINANCE_BASE_URL=https://testnet.binance.vision
  4. The testnet auto-funds with 10,000 USDT

ALPACA (paper trading — free, no real money):
  1. Sign up: https://alpaca.markets
  2. Go to Paper Trading section → generate API key
  3. Add to .env.test:
       ALPACA_API_KEY=PKxxx
       ALPACA_API_SECRET=your_secret
       ALPACA_BASE_URL=https://paper-api.alpaca.markets

OANDA (practice account — free, no real money):
  1. Sign up: https://www.oanda.com/register
  2. Dashboard → Manage API Access → Generate Token
  3. Find your practice account ID in the platform
  4. Add to .env.test:
       OANDA_API_KEY=your_token
       OANDA_ACCOUNT_ID=your_practice_account_id
       OANDA_BASE_URL=https://api-fxpractice.oanda.com

Run all exchange tests:
    pytest tests/test_exchanges_live.py -v

Run one exchange only:
    pytest tests/test_exchanges_live.py -v -k binance
═══════════════════════════════════════════════════════════
"""

import os

import pytest
import pytest_asyncio

pytestmark = [pytest.mark.live, pytest.mark.exchange]

# ─────────────────────────────────────────────────────────────────────────────
# BINANCE TESTNET TESTS
# ─────────────────────────────────────────────────────────────────────────────

class TestBinanceLive:
    """Tests against Binance testnet (https://testnet.binance.vision)."""

    @pytest.fixture(autouse=True)
    def _check_keys(self, require_binance):  # noqa: F811
        pass

    @pytest.fixture
    async def client(self):
        """Binance testnet client. Uses BINANCE_BASE_URL if set (for testnet override)."""
        import httpx
        from src.integrations.exchange_client import BinanceClient

        api_key    = os.environ["BINANCE_API_KEY"]
        api_secret = os.environ["BINANCE_API_SECRET"]

        c = BinanceClient(api_key, api_secret)
        # Override base URL to testnet if env var is set
        testnet_url = os.getenv("BINANCE_BASE_URL", "https://api.binance.com")
        if testnet_url != "https://api.binance.com":
            await c._http.aclose()
            c._http = httpx.AsyncClient(
                base_url=testnet_url,
                headers={"X-MBX-APIKEY": api_key},
                timeout=15.0,
            )
        yield c
        await c.aclose()

    @pytest.mark.asyncio
    async def test_get_account_balance(self, client):
        """Testnet account should have USDT balance auto-seeded by Binance."""
        balance = await client.get_account_balance()
        print(f"\n  Binance USDT balance: {balance:.2f}")
        assert isinstance(balance, float), "Balance must be a float"
        assert balance >= 0, "Balance cannot be negative"

    @pytest.mark.asyncio
    async def test_get_btc_price(self, client):
        """BTC/USDT price should be a reasonable positive number."""
        price = await client.get_current_price("BTCUSDT")
        print(f"\n  BTC/USDT price: ${price:,.2f}")
        assert price > 0, "Price must be positive"
        assert price < 10_000_000, "Price is unrealistically high — check symbol"

    @pytest.mark.asyncio
    async def test_get_eth_price(self, client):
        """ETH/USDT price sanity check."""
        price = await client.get_current_price("ETHUSDT")
        print(f"\n  ETH/USDT price: ${price:,.2f}")
        assert price > 0
        assert price < 100_000

    @pytest.mark.asyncio
    async def test_get_open_orders_empty(self, client):
        """Fresh testnet account should have no open orders."""
        orders = await client.get_open_orders("BTCUSDT")
        print(f"\n  Open BTC orders: {len(orders)}")
        assert isinstance(orders, list), "Should return a list"

    @pytest.mark.asyncio
    async def test_market_ticker_response_shape(self, client):
        """Verify the price endpoint returns the expected data shape."""
        import httpx
        resp = await client._http.get("/api/v3/ticker/price", params={"symbol": "BTCUSDT"})
        resp.raise_for_status()
        data = resp.json()
        assert "symbol" in data, "Response should have 'symbol'"
        assert "price" in data, "Response should have 'price'"
        assert data["symbol"] == "BTCUSDT"

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        not os.getenv("BINANCE_RUN_ORDER_TEST"),
        reason="Order placement test disabled by default — set BINANCE_RUN_ORDER_TEST=1 to enable",
    )
    async def test_place_and_cancel_limit_order(self, client):
        """Place a far-off-market limit buy order and immediately cancel it."""
        # Get current price to set a limit far below market (won't fill)
        price = await client.get_current_price("BTCUSDT")
        limit_price = round(price * 0.50, 2)  # 50% below market — safe, won't fill

        print(f"\n  Placing limit BUY at ${limit_price:,.2f} (50% below market)")
        order_id = await client.place_order("BTCUSDT", "BUY", 0.001, price=limit_price)
        assert order_id, "Should return an order ID"
        print(f"  Order placed: {order_id}")

        # Verify order status
        status = await client.get_order_status("BTCUSDT", order_id)
        print(f"  Order status: {status['status']}")
        assert status["status"] in ("NEW", "PARTIALLY_FILLED"), "Order should be open"

        # Cancel to clean up testnet
        await client._delete("/api/v3/order", {"symbol": "BTCUSDT", "orderId": order_id})
        print(f"  Order cancelled cleanly.")


# ─────────────────────────────────────────────────────────────────────────────
# ALPACA PAPER TRADING TESTS
# ─────────────────────────────────────────────────────────────────────────────

class TestAlpacaLive:
    """Tests against Alpaca paper trading environment."""

    @pytest.fixture(autouse=True)
    def _check_keys(self, require_alpaca):  # noqa: F811
        pass

    @pytest.fixture
    async def client(self):
        from src.integrations.exchange_client import AlpacaClient
        c = AlpacaClient(
            api_key=os.environ["ALPACA_API_KEY"],
            api_secret=os.environ["ALPACA_API_SECRET"],
            base_url=os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets"),
        )
        yield c
        await c.aclose()

    @pytest.mark.asyncio
    async def test_get_paper_account_balance(self, client):
        """Paper account is seeded with $100,000 cash by Alpaca."""
        balance = await client.get_account_balance()
        print(f"\n  Alpaca paper cash balance: ${balance:,.2f}")
        assert isinstance(balance, float)
        assert balance >= 0

    @pytest.mark.asyncio
    async def test_account_details_shape(self, client):
        """Verify account endpoint returns required fields."""
        data = await client._get("/v2/account")
        assert "id" in data,          "Account should have 'id'"
        assert "cash" in data,        "Account should have 'cash'"
        assert "status" in data,      "Account should have 'status'"
        assert data["status"] == "ACTIVE", f"Account status should be ACTIVE, got {data['status']}"
        print(f"\n  Alpaca account id: {data['id']} status: {data['status']}")

    @pytest.mark.asyncio
    async def test_get_aapl_price(self, client):
        """Get AAPL (Apple) bid/ask price from data endpoint."""
        data = await client._get("/v2/stocks/AAPL/quotes/latest")
        quote = data.get("quote", {})
        bid = float(quote.get("bp", 0))
        ask = float(quote.get("ap", 0))
        mid = (bid + ask) / 2 if bid and ask else 0
        print(f"\n  AAPL bid={bid:.2f} ask={ask:.2f} mid={mid:.2f}")
        assert mid > 0, "AAPL should have a positive price"

    @pytest.mark.asyncio
    async def test_get_open_orders_empty(self, client):
        """Should return a list (may or may not be empty)."""
        orders = await client.get_open_orders("AAPL")
        print(f"\n  Alpaca open AAPL orders: {len(orders)}")
        assert isinstance(orders, list)

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        not os.getenv("ALPACA_RUN_ORDER_TEST"),
        reason="Order test disabled by default — set ALPACA_RUN_ORDER_TEST=1 to enable",
    )
    async def test_place_and_cancel_limit_order(self, client):
        """Place a far-off-market limit order on paper and cancel it."""
        import httpx
        # Get a price for AAPL
        data = await client._get("/v2/stocks/AAPL/quotes/latest")
        ask = float(data.get("quote", {}).get("ap", 200))
        limit_price = round(ask * 0.50, 2)  # 50% below — won't fill

        print(f"\n  Placing Alpaca limit BUY AAPL @ ${limit_price:.2f}")
        order_id = await client.place_order("AAPL", "BUY", 1, price=limit_price)
        assert order_id, "Should return order ID"
        print(f"  Order ID: {order_id}")

        status = await client.get_order_status("AAPL", order_id)
        assert status["status"] in ("new", "accepted", "pending_new")

        # Cancel cleanly
        await client._delete(f"/v2/orders/{order_id}")
        print("  Order cancelled.")


# ─────────────────────────────────────────────────────────────────────────────
# OANDA PRACTICE TESTS
# ─────────────────────────────────────────────────────────────────────────────

class TestOandaLive:
    """Tests against OANDA practice (paper) environment."""

    @pytest.fixture(autouse=True)
    def _check_keys(self, require_oanda):  # noqa: F811
        pass

    @pytest.fixture
    async def client(self):
        from src.integrations.exchange_client import OandaClient
        c = OandaClient(
            api_key=os.environ["OANDA_API_KEY"],
            api_secret="",
            account_id=os.environ["OANDA_ACCOUNT_ID"],
        )
        yield c
        await c.aclose()

    @pytest.mark.asyncio
    async def test_get_practice_balance(self, client):
        """Practice account has seeded balance."""
        balance = await client.get_account_balance()
        print(f"\n  OANDA practice balance: {balance:.2f}")
        assert isinstance(balance, float)
        assert balance >= 0

    @pytest.mark.asyncio
    async def test_get_eurusd_price(self, client):
        """EUR_USD should return a valid mid price (around 1.05-1.15)."""
        price = await client.get_current_price("EUR_USD")
        print(f"\n  EUR_USD mid price: {price:.5f}")
        assert price > 0, "Price must be positive"
        assert 0.8 < price < 1.5, f"EUR_USD sanity check failed: {price}"

    @pytest.mark.asyncio
    async def test_get_gbpusd_price(self, client):
        """GBP_USD sanity check."""
        price = await client.get_current_price("GBP_USD")
        print(f"\n  GBP_USD mid price: {price:.5f}")
        assert 0.8 < price < 2.0

    @pytest.mark.asyncio
    async def test_account_summary_shape(self, client):
        """Verify account summary has required fields."""
        data = await client._get(f"/v3/accounts/{client._account_id}/summary")
        account = data.get("account", {})
        assert "balance" in account, "Account should have 'balance'"
        assert "currency" in account, "Account should have 'currency'"
        print(f"\n  OANDA currency: {account['currency']} balance: {account['balance']}")

    @pytest.mark.asyncio
    async def test_get_open_orders(self, client):
        """Open orders endpoint should return a list."""
        orders = await client.get_open_orders("EUR_USD")
        print(f"\n  OANDA open EUR_USD orders: {len(orders)}")
        assert isinstance(orders, list)


# ─────────────────────────────────────────────────────────────────────────────
# CROSS-EXCHANGE: Public Market Data (no auth required)
# ─────────────────────────────────────────────────────────────────────────────

class TestPublicMarketData:
    """Test public market data endpoints — no API keys required."""

    @pytest.mark.asyncio
    async def test_binance_public_btc_price(self):
        """Binance public ticker endpoint — no auth needed."""
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as http:
            resp = await http.get(
                "https://api.binance.com/api/v3/ticker/price",
                params={"symbol": "BTCUSDT"},
            )
        resp.raise_for_status()
        data = resp.json()
        price = float(data["price"])
        print(f"\n  BTC/USDT (public): ${price:,.2f}")
        assert price > 1_000, "BTC should be above $1,000"

    @pytest.mark.asyncio
    async def test_full_market_analysis_binance(self):
        """Full indicator pipeline should return RSI, MACD, support/resistance."""
        from src.integrations.market_data import full_market_analysis
        data = await full_market_analysis("BTCUSDT", "binance")

        print(f"\n  Market analysis snapshot:")
        print(f"    price        = ${data.get('price', 0):,.2f}")
        print(f"    trend        = {data.get('trend')}")
        print(f"    RSI(14)      = {data.get('indicators', {}).get('rsi', 'N/A'):.1f}")
        print(f"    MA(20/50)    = {data.get('indicators', {}).get('ma20', 0):,.2f} / {data.get('indicators', {}).get('ma50', 0):,.2f}")

        # Structural assertions
        assert "price" in data and data["price"] > 0
        assert "trend" in data and data["trend"] in ("uptrend", "downtrend", "sideways")
        assert "indicators" in data
        indicators = data["indicators"]
        assert 0 <= indicators.get("rsi", -1) <= 100, "RSI must be 0-100"
        assert "ma20" in indicators
        assert "ma50" in indicators
        assert "ma200" in indicators
        assert "support_resistance" in data
        sr = data["support_resistance"]
        assert "support" in sr
        assert "resistance" in sr
        assert sr["support"] < data["price"], "Support should be below current price"
        assert sr["resistance"] > data["price"], "Resistance should be above current price"

    @pytest.mark.asyncio
    async def test_market_data_factory_all_exchanges(self):
        """get_exchange_client factory returns correct types for all exchanges."""
        from src.integrations.exchange_client import (
            get_exchange_client,
            BinanceClient, AlpacaClient, OandaClient,
        )
        b = get_exchange_client("binance", "key", "secret")
        a = get_exchange_client("alpaca",  "key", "secret")
        o = get_exchange_client("oanda",   "key", "secret")

        assert isinstance(b, BinanceClient)
        assert isinstance(a, AlpacaClient)
        assert isinstance(o, OandaClient)

        with pytest.raises(ValueError, match="Unsupported exchange"):
            get_exchange_client("kraken", "key", "secret")

        await b.aclose()
        await a.aclose()
        await o.aclose()
