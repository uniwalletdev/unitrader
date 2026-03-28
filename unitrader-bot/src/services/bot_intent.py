"""
Lightweight intent routing for Telegram/WhatsApp free text.

Maps natural phrases to the same command handlers as explicit keywords,
or falls back to orchestrator chat (onboarding vs trading parity with web).
"""

from __future__ import annotations

import re
from typing import Any

# WhatsApp first-token commands (lowercase) — must match dispatcher.
WHATSAPP_LITERAL_COMMANDS = frozenset(
    {
        "start",
        "link",
        "portfolio",
        "trade",
        "close",
        "history",
        "performance",
        "chat",
        "alerts",
        "settings",
        "unlink",
        "help",
    }
)


def classify_natural_intent(message: str) -> dict[str, Any]:
    """Classify free-text (no leading / on Telegram; any non-literal on WhatsApp).

    Returns:
        {"route": "command", "command": str, "args": list[str]}
        {"route": "orchestrator_chat", "message": str}
    """
    text = (message or "").strip()
    if not text:
        return {"route": "orchestrator_chat", "message": text}

    low = text.lower()

    # Natural trade: "trade buy BTC-USD 1.5" / "trade sell ETHUSDT 0.5"
    m = re.match(
        r"^\s*trade\s+(buy|sell)\s+([A-Za-z0-9./\-_]+)\s+(\d+(?:\.\d+)?)\s*$",
        low,
    )
    if m:
        return {
            "route": "command",
            "command": "trade",
            "args": [m.group(1).upper(), m.group(2).upper().replace("/", ""), m.group(3)],
        }

    # Natural close: "close BTCUSDT"
    m = re.match(r"^\s*close\s+([A-Za-z0-9./\-_]+)\s*$", low)
    if m:
        sym = m.group(1).upper().replace("/", "")
        return {"route": "command", "command": "close", "args": [sym]}

    # Portfolio-style queries (keep short to reduce false positives)
    if len(low) <= 160:
        if re.match(
            r"^(?:show\s+)?(?:my\s+)?(?:open\s+)?(?:positions?|holdings|portfolio)\s*\.?$",
            low,
        ):
            return {"route": "command", "command": "portfolio", "args": []}
        if re.search(
            r"\b(?:what|show)\s+(?:are\s+)?(?:my\s+)?(?:open\s+)?(?:positions?|holdings)\b",
            low,
        ):
            return {"route": "command", "command": "portfolio", "args": []}

    # Performance / stats
    if len(low) <= 180 and re.search(
        r"\b(?:win\s*rate|my\s+stats?|performance|p\s*&\s*l|pnl|how\s+(?:am\s+i|have\s+i)\s+doing)\b",
        low,
    ):
        return {"route": "command", "command": "performance", "args": []}

    # Trade history
    if len(low) <= 160 and re.search(
        r"\b(?:trade\s+history|past\s+trades|closed\s+trades|my\s+history|recent\s+trades)\b",
        low,
    ):
        return {"route": "command", "command": "history", "args": []}

    return {"route": "orchestrator_chat", "message": text}
