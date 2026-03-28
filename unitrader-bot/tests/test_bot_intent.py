"""Unit tests for src.services.bot_intent.classify_natural_intent."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.mark.parametrize(
    "text,command,args",
    [
        ("show my portfolio", "portfolio", []),
        ("What are my open positions?", "portfolio", []),
        ("trade buy BTCUSDT 1.5", "trade", ["BUY", "BTCUSDT", "1.5"]),
        ("TRADE SELL ETHUSDT 0.5", "trade", ["SELL", "ETHUSDT", "0.5"]),
        ("close BTCUSDT", "close", ["BTCUSDT"]),
        ("what's my win rate", "performance", []),
        ("show my trade history", "history", []),
    ],
)
def test_classify_routes_to_command(text, command, args):
    from src.services.bot_intent import classify_natural_intent

    out = classify_natural_intent(text)
    assert out["route"] == "command"
    assert out["command"] == command
    assert out.get("args", []) == args


def test_classify_falls_back_to_orchestrator_chat():
    from src.services.bot_intent import classify_natural_intent

    out = classify_natural_intent("Explain moving averages in simple terms")
    assert out["route"] == "orchestrator_chat"
    assert out["message"] == "Explain moving averages in simple terms"


def test_whatsapp_literal_set_includes_help():
    from src.services.bot_intent import WHATSAPP_LITERAL_COMMANDS

    assert "help" in WHATSAPP_LITERAL_COMMANDS
    assert "portfolio" in WHATSAPP_LITERAL_COMMANDS
