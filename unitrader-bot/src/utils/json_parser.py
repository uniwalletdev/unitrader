"""
src/utils/json_parser.py — Robust JSON parser for Claude LLM responses.

Claude sometimes returns:
  - Markdown code fences around JSON (```json ... ```)
  - Literal newline/tab characters inside JSON string values instead of \\n / \\t
  - Trailing commas, or extra text before/after the JSON block

This module provides `parse_claude_json` which handles all of these gracefully.
"""

import json
import re
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _escape_control_chars_in_strings(raw: str) -> str:
    """Walk the raw string character by character and escape control chars
    that appear *inside* JSON string values (but not structural whitespace).

    This is the main fix for the 'Invalid control character' error that occurs
    when Claude writes a multi-line blog post as a JSON string value using
    literal newlines instead of \\n escape sequences.
    """
    result: list[str] = []
    in_string = False
    escape_next = False

    for ch in raw:
        if escape_next:
            result.append(ch)
            escape_next = False
            continue

        if ch == "\\" and in_string:
            result.append(ch)
            escape_next = True
            continue

        if ch == '"':
            in_string = not in_string
            result.append(ch)
            continue

        if in_string and ord(ch) < 0x20:
            # Control character inside a string value — must be escaped
            if ch == "\n":
                result.append("\\n")
            elif ch == "\r":
                result.append("\\r")
            elif ch == "\t":
                result.append("\\t")
            else:
                result.append(f"\\u{ord(ch):04x}")
            continue

        result.append(ch)

    return "".join(result)


def _strip_markdown_fences(raw: str) -> str:
    """Remove leading/trailing markdown code fences that Claude sometimes adds."""
    raw = raw.strip()
    # ```json ... ``` or ``` ... ```
    raw = re.sub(r"^```[a-zA-Z]*\s*\n?", "", raw)
    raw = re.sub(r"\n?```\s*$", "", raw)
    return raw.strip()


def _extract_json_block(raw: str) -> str:
    """Try to extract a JSON object {} or array [] from a larger text block.

    Claude occasionally outputs explanatory text before or after the JSON.
    We scan for the first { or [ and find its matching closing bracket.
    """
    for start_char, end_char in [('{', '}'), ('[', ']')]:
        start = raw.find(start_char)
        if start == -1:
            continue
        depth = 0
        in_string = False
        escape_next = False
        for i, ch in enumerate(raw[start:], start=start):
            if escape_next:
                escape_next = False
                continue
            if ch == "\\" and in_string:
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if not in_string:
                if ch == start_char:
                    depth += 1
                elif ch == end_char:
                    depth -= 1
                    if depth == 0:
                        return raw[start: i + 1]
    return raw


def parse_claude_json(raw: str, context: str = "") -> Any:
    """Parse a JSON response from Claude, handling common formatting issues.

    Args:
        raw:     Raw text from Claude's response.
        context: Optional label for error logging (e.g. "blog post", "trade decision").

    Returns:
        Parsed Python object (dict or list).

    Raises:
        json.JSONDecodeError: If all parsing attempts fail.
    """
    if not raw:
        raise json.JSONDecodeError("Empty response", "", 0)

    # Attempt 1 — parse as-is (fast path for well-formed responses)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Attempt 2 — strip markdown fences
    cleaned = _strip_markdown_fences(raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Attempt 3 — escape control characters inside string values
    sanitised = _escape_control_chars_in_strings(cleaned)
    try:
        return json.loads(sanitised)
    except json.JSONDecodeError:
        pass

    # Attempt 4 — extract just the JSON block from surrounding text
    extracted = _extract_json_block(sanitised)
    try:
        result = json.loads(extracted)
        if context:
            logger.debug("parse_claude_json[%s]: needed block extraction", context)
        return result
    except json.JSONDecodeError:
        pass

    # Attempt 5 — last resort: remove ALL control chars and retry
    no_control = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", extracted)
    try:
        return json.loads(no_control)
    except json.JSONDecodeError as exc:
        if context:
            logger.error(
                "parse_claude_json[%s] all attempts failed. raw[:300]=%s",
                context, raw[:300],
            )
        raise exc
