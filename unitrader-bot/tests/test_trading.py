"""
tests/test_trading.py — Unit tests for the trading engine.

Run with:  pytest tests/test_trading.py -v

Tests are grouped by module:
  - trade_execution.py  (pure calculations — no I/O)
  - market_data.py      (indicator calculations — no I/O)
  - trading_agent.py    (safety checks, personalisation)
"""

import pytest

from src.services.trade_execution import (
    build_trade_parameters,
    calculate_position_size,
    calculate_quantity,
    calculate_risk_reward,
    calculate_stop_loss,
    calculate_take_profit,
)
from src.integrations.market_data import (
    calculate_indicators,
    calculate_macd,
    calculate_moving_averages,
    calculate_rsi,
    calculate_support_resistance,
    detect_trend,
)


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _prices(n: int = 200, start: float = 100.0, step: float = 0.5) -> list[float]:
    """Generate a simple ascending price series."""
    return [round(start + i * step, 4) for i in range(n)]


def _descending_prices(n: int = 200, start: float = 200.0, step: float = 0.5) -> list[float]:
    return [round(start - i * step, 4) for i in range(n)]


# ═════════════════════════════════════════════
# POSITION SIZING
# ═════════════════════════════════════════════

class TestPositionSizing:
    def test_below_threshold_no_trade(self):
        result = calculate_position_size(confidence=40, account_balance=10_000)
        assert result["tradeable"] is False
        assert result["size_amount"] == 0.0

    def test_exactly_50_is_tradeable(self):
        result = calculate_position_size(confidence=50, account_balance=10_000)
        assert result["tradeable"] is True
        assert result["size_percent"] == 0.5

    def test_confidence_65_to_75(self):
        result = calculate_position_size(confidence=70, account_balance=10_000)
        assert result["size_percent"] == 1.0
        assert result["size_amount"] == 100.0

    def test_confidence_75_to_85(self):
        result = calculate_position_size(confidence=80, account_balance=10_000)
        assert result["size_percent"] == 1.5
        assert result["size_amount"] == 150.0

    def test_high_confidence_max_2pct(self):
        result = calculate_position_size(confidence=90, account_balance=10_000)
        assert result["size_percent"] == 2.0
        assert result["size_amount"] == 200.0

    def test_large_balance(self):
        result = calculate_position_size(confidence=85, account_balance=100_000)
        assert result["size_amount"] == 2000.0


# ═════════════════════════════════════════════
# STOP LOSS
# ═════════════════════════════════════════════

class TestStopLoss:
    def test_buy_stop_2pct_below(self):
        result = calculate_stop_loss(entry_price=45_000, side="BUY")
        assert result["stop_loss"] == pytest.approx(44_100, rel=1e-4)
        assert result["stop_pct"] == 2.0

    def test_sell_stop_2pct_above(self):
        result = calculate_stop_loss(entry_price=45_000, side="SELL")
        assert result["stop_loss"] == pytest.approx(45_900, rel=1e-4)

    def test_custom_stop_pct(self):
        result = calculate_stop_loss(entry_price=100, side="BUY", stop_pct=5.0)
        assert result["stop_loss"] == pytest.approx(95.0, rel=1e-4)

    def test_max_loss_calculated(self):
        result = calculate_stop_loss(entry_price=45_000, side="BUY", stop_pct=2.0, position_size_usd=1000)
        assert result["max_loss_usd"] == pytest.approx(20.0, rel=1e-4)


# ═════════════════════════════════════════════
# TAKE PROFIT
# ═════════════════════════════════════════════

class TestTakeProfit:
    def test_buy_target_6pct_above(self):
        result = calculate_take_profit(entry_price=45_000, side="BUY")
        assert result["take_profit"] == pytest.approx(47_700, rel=1e-4)
        assert result["target_pct"] == 6.0

    def test_sell_target_6pct_below(self):
        result = calculate_take_profit(entry_price=45_000, side="SELL")
        assert result["take_profit"] == pytest.approx(42_300, rel=1e-4)

    def test_max_gain_calculated(self):
        result = calculate_take_profit(entry_price=45_000, side="BUY", target_pct=6.0, position_size_usd=1000)
        assert result["max_gain_usd"] == pytest.approx(60.0, rel=1e-4)


# ═════════════════════════════════════════════
# RISK / REWARD
# ═════════════════════════════════════════════

class TestRiskReward:
    def test_3to1_ratio(self):
        rr = calculate_risk_reward(entry=100, stop=98, target=106)
        assert rr == pytest.approx(3.0, rel=1e-4)

    def test_zero_risk_returns_zero(self):
        rr = calculate_risk_reward(entry=100, stop=100, target=106)
        assert rr == 0.0

    def test_1to1_ratio(self):
        rr = calculate_risk_reward(entry=100, stop=98, target=102)
        assert rr == pytest.approx(1.0, rel=1e-4)


# ═════════════════════════════════════════════
# QUANTITY
# ═════════════════════════════════════════════

class TestQuantity:
    def test_basic_quantity(self):
        qty = calculate_quantity(position_size_usd=1000, price=50_000)
        assert qty == pytest.approx(0.02, rel=1e-4)

    def test_zero_price_returns_zero(self):
        assert calculate_quantity(1000, 0) == 0.0


# ═════════════════════════════════════════════
# BUILD TRADE PARAMETERS
# ═════════════════════════════════════════════

class TestBuildTradeParameters:
    def test_full_build_buy(self):
        params = build_trade_parameters(
            confidence=80,
            entry_price=45_000,
            side="BUY",
            account_balance=10_000,
        )
        assert params["tradeable"] is True
        assert params["size_percent"] == 1.5
        assert params["stop_loss"] < 45_000
        assert params["take_profit"] > 45_000
        assert params["risk_reward"] > 0

    def test_low_confidence_not_tradeable(self):
        params = build_trade_parameters(
            confidence=30,
            entry_price=45_000,
            side="BUY",
            account_balance=10_000,
        )
        assert params["tradeable"] is False

    def test_full_build_sell(self):
        params = build_trade_parameters(
            confidence=85,
            entry_price=45_000,
            side="SELL",
            account_balance=10_000,
        )
        assert params["tradeable"] is True
        assert params["stop_loss"] > 45_000
        assert params["take_profit"] < 45_000


# ═════════════════════════════════════════════
# RSI
# ═════════════════════════════════════════════

class TestRSI:
    def test_insufficient_data_returns_50(self):
        assert calculate_rsi([100, 101, 102], period=14) == 50.0

    def test_all_gains_returns_100(self):
        prices = [float(i) for i in range(1, 30)]
        rsi = calculate_rsi(prices, period=14)
        assert rsi > 90

    def test_all_losses_returns_low(self):
        prices = [float(30 - i) for i in range(30)]
        rsi = calculate_rsi(prices, period=14)
        assert rsi < 10

    def test_neutral_returns_near_50(self):
        # Alternating up/down
        prices = [100 + (1 if i % 2 == 0 else -1) for i in range(50)]
        rsi = calculate_rsi(prices, period=14)
        assert 40 < rsi < 60


# ═════════════════════════════════════════════
# MACD
# ═════════════════════════════════════════════

class TestMACD:
    def test_insufficient_data_returns_zeros(self):
        result = calculate_macd([100.0] * 10)
        assert result == {"line": 0.0, "signal": 0.0, "histogram": 0.0}

    def test_uptrend_positive_histogram(self):
        prices = _prices(100, start=100.0, step=1.0)
        result = calculate_macd(prices)
        assert result["histogram"] > 0

    def test_returns_expected_keys(self):
        prices = _prices(100)
        result = calculate_macd(prices)
        assert "line" in result
        assert "signal" in result
        assert "histogram" in result


# ═════════════════════════════════════════════
# MOVING AVERAGES
# ═════════════════════════════════════════════

class TestMovingAverages:
    def test_returns_all_keys(self):
        prices = _prices(200)
        result = calculate_moving_averages(prices)
        assert "ma20" in result
        assert "ma50" in result
        assert "ma200" in result

    def test_uptrend_ma20_above_ma200(self):
        prices = _prices(210, start=100.0, step=0.5)
        result = calculate_moving_averages(prices)
        assert result["ma20"] > result["ma200"]

    def test_insufficient_data_uses_last_price(self):
        prices = [50.0] * 5
        result = calculate_moving_averages(prices)
        assert result["ma20"] == 50.0


# ═════════════════════════════════════════════
# TREND DETECTION
# ═════════════════════════════════════════════

class TestTrendDetection:
    def test_uptrend(self):
        prices = _prices(200, step=1.0)
        assert detect_trend(prices) == "uptrend"

    def test_downtrend(self):
        prices = _descending_prices(200, step=1.0)
        assert detect_trend(prices) == "downtrend"

    def test_insufficient_data_is_consolidating(self):
        assert detect_trend([100.0] * 10) == "consolidating"

    def test_flat_is_consolidating(self):
        prices = [100.0 + (i % 3) * 0.1 for i in range(200)]
        assert detect_trend(prices) == "consolidating"


# ═════════════════════════════════════════════
# SUPPORT / RESISTANCE
# ═════════════════════════════════════════════

class TestSupportResistance:
    def test_returns_all_keys(self):
        prices = _prices(50)
        result = calculate_support_resistance(prices)
        assert "support" in result
        assert "resistance" in result
        assert "pivot" in result

    def test_support_below_resistance(self):
        prices = _prices(50)
        result = calculate_support_resistance(prices)
        assert result["support"] <= result["pivot"] <= result["resistance"]

    def test_single_price(self):
        result = calculate_support_resistance([100.0])
        assert result["pivot"] == 100.0


# ═════════════════════════════════════════════
# CALCULATE INDICATORS (bundle)
# ═════════════════════════════════════════════

class TestCalculateIndicators:
    def test_returns_all_expected_keys(self):
        prices = _prices(200)
        result = calculate_indicators(prices)
        assert "rsi" in result
        assert "macd" in result
        assert "ma20" in result
        assert "ma50" in result
        assert "ma200" in result

    def test_rsi_in_valid_range(self):
        prices = _prices(200)
        result = calculate_indicators(prices)
        assert 0 <= result["rsi"] <= 100
