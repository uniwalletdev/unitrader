"""
tests/test_signal_notification_dispatch.py — Unit tests for high-confidence signal alerts.

Run:
    pytest tests/test_signal_notification_dispatch.py -v --asyncio-mode=auto
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _mk_engine(telegram_ok: bool = True, whatsapp_ok: bool = True):
    telegram_bot = SimpleNamespace(
        app=SimpleNamespace(
            bot=SimpleNamespace(
                send_message=AsyncMock(
                    side_effect=None if telegram_ok else Exception("telegram down")
                )
            )
        )
    )
    whatsapp_bot = SimpleNamespace(
        send_message=AsyncMock(
            side_effect=None if whatsapp_ok else Exception("whatsapp down")
        )
    )
    return SimpleNamespace(telegram_bot=telegram_bot, whatsapp_bot=whatsapp_bot)


class _DB:
    def __init__(self, execute_results):
        self._results = list(execute_results)
        self.add = MagicMock()
        self.flush = AsyncMock()

    async def execute(self, *_args, **_kwargs):
        return self._results.pop(0)


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


@pytest.mark.asyncio
async def test_dispatch_filters_recipients_and_sends_concurrently(monkeypatch):
    from src.services.signal_notification_dispatch import dispatch_signal_notification
    from src.services.unitrader_notifications import set_unitrader_notification_engine

    engine = _mk_engine(telegram_ok=True, whatsapp_ok=True)
    set_unitrader_notification_engine(engine)

    # execute() calls order:
    # 1) dedupe ids query -> empty
    # 2) recipients query -> rows
    db = _DB(
        execute_results=[
            _Result([]),
            _Result(
                [
                    # eligible telegram
                    ("u1", 75, "telegram", "tg_chat_1", {"notifications": True}),
                    # too strict threshold
                    ("u2", 95, "telegram", "tg_chat_2", {"notifications": True}),
                    # disabled via per-platform setting
                    ("u3", 50, "whatsapp", "+447700900000", {"notifications": False}),
                ]
            ),
        ]
    )

    res = await dispatch_signal_notification(
        {
            "symbol": "AAPL",
            "direction": "BUY",
            "confidence": 87,
            "exchange": "alpaca",
            "price": 192.34,
            "reasoning": "Test reasoning",
        },
        db,
    )

    assert res["sent_telegram"] == 1
    assert res["sent_whatsapp"] == 0
    assert res["errors"] == []
    assert engine.telegram_bot.app.bot.send_message.await_count == 1
    assert engine.whatsapp_bot.send_message.await_count == 0
    assert db.add.call_count == 1  # AuditLog row


@pytest.mark.asyncio
async def test_dispatch_collects_send_errors(monkeypatch):
    from src.services.signal_notification_dispatch import dispatch_signal_notification
    from src.services.unitrader_notifications import set_unitrader_notification_engine

    engine = _mk_engine(telegram_ok=False, whatsapp_ok=False)
    set_unitrader_notification_engine(engine)

    db = _DB(
        execute_results=[
            _Result([]),
            _Result(
                [
                    ("u1", 75, "telegram", "tg_chat_1", {"notifications": True}),
                    ("u1", 75, "whatsapp", "+447700900000", {"notifications": True}),
                ]
            ),
        ]
    )

    res = await dispatch_signal_notification(
        {
            "symbol": "BTC/USD",
            "direction": "SELL",
            "confidence": 80,
            "exchange": "coinbase",
            "price": 60000,
            "reasoning": "Test reasoning",
        },
        db,
    )

    assert res["sent_telegram"] == 0
    assert res["sent_whatsapp"] == 0
    assert len(res["errors"]) == 2
    assert {e["channel"] for e in res["errors"]} == {"telegram", "whatsapp"}

