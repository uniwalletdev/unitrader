"""Regression guard: no production code path may hardcode the retired
``claude-3-haiku-20240307`` literal.

Anthropic retired Haiku 3 on 2026-04-20. Every agent and router that used
the string literal was migrated to ``settings.anthropic_model_fast`` so the
next deprecation is a one-line env flip. This test prevents silent
re-introduction of a hardcoded model id.

Allowed locations for the literal:
    * ``src/agents/token_manager/pricing.py`` — historical price ledger
      keyed by model id; must retain Haiku 3 so past ``token_usage`` rows
      still cost-compute correctly.
    * ``tests/`` — pricing tests assert historical Haiku 3 pricing.
    * ``DOCUMENTATION.md`` — changelog row.
    * ``deployment/migrations/`` — historical/forward-only migration SQL.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_RETIRED_MODEL = "claude-3-haiku-20240307"
_SCAN_DIRS = ("src", "routers", "main.py", "config.py", "models.py")
_ALLOWED_PATHS = {
    ("src", "agents", "token_manager", "pricing.py"),
}


def _iter_python_files() -> list[Path]:
    files: list[Path] = []
    for target in _SCAN_DIRS:
        p = _REPO_ROOT / target
        if p.is_file() and p.suffix == ".py":
            files.append(p)
        elif p.is_dir():
            files.extend(p.rglob("*.py"))
    return files


def _is_allowed(path: Path) -> bool:
    parts = path.relative_to(_REPO_ROOT).parts
    return parts in _ALLOWED_PATHS


def test_anthropic_model_fast_default_is_haiku_4_5():
    """The default in config.py must be Haiku 4.5 (not the retired Haiku 3)."""
    from config import Settings

    assert Settings().anthropic_model_fast == "claude-haiku-4-5-20251001"


def test_no_hardcoded_retired_haiku_in_production_code():
    """Scan production source trees for the retired Haiku 3 string literal.

    Any match outside the allowlist (pricing ledger) is a regression — the
    callsite should reference ``settings.anthropic_model_fast`` instead.
    """
    offenders: list[str] = []
    for py_file in _iter_python_files():
        if _is_allowed(py_file):
            continue
        try:
            text = py_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if _RETIRED_MODEL in text:
            offenders.append(str(py_file.relative_to(_REPO_ROOT)))

    assert not offenders, (
        f"Retired model id '{_RETIRED_MODEL}' found in production source:\n"
        + "\n".join(f"  - {o}" for o in offenders)
        + "\n\nReplace with `settings.anthropic_model_fast`. If this literal "
        "is intentionally retained (e.g. for historical pricing), add the "
        "file path to `_ALLOWED_PATHS` in this test."
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
