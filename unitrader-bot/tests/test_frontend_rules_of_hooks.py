"""
tests/test_frontend_rules_of_hooks.py

Lightweight static regression guard for the React Rules-of-Hooks violations
that manifested as React error #310 in production ("Rendered more hooks
than during the previous render").

The frontend has NO JS test infrastructure (no jest/vitest/testing-library
in frontend/package.json), so we can't run an actual render-transition
test. Instead we parse the two files that contained the original bugs and
assert that, inside each exported React component body, no hook call
(useState / useEffect / useMemo / useCallback / useRef / useContext)
appears AFTER an early-return statement. This is the exact invariant that
Rules of Hooks requires and the one that React error #310 enforces at
runtime.

Future work (logged in docs/roadmap.md): adding @testing-library/react
would let us write a proper render-transition test that mounts
TrustLadderDetail, toggles `traderClass` from null → "complete_novice" in
a mocked getSettings response, and asserts no #310 is thrown. Decide
whether that cost is worth the coverage.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).parent.parent
FRONTEND_COMPONENTS = REPO_ROOT / "frontend" / "components"

HOOK_CALL_RE = re.compile(
    r"\b(useState|useEffect|useMemo|useCallback|useRef|useContext)\s*[(<]"
)

# Matches an early-return at function-body indent (2 or 4 spaces), whether
# it returns null, JSX (e.g. `<CompactBar />`), or a helper call.
# Intentionally conservative: only flags lines that start with whitespace +
# `if (...) return <expr>` or just `return <expr>;` at that level. Multi-line
# returns are matched on the `return` line.
EARLY_RETURN_RE = re.compile(
    r"""^
        [ ]{2,4}                      # function body indent
        (?: if\s*\([^)]+\)\s*return   # conditional early return
          | return                    # or unconditional return (rare in components)
        )
        \s+                           # then at least one space before the returned expression
        (?!.*\bfunction\b)            # rule out `return function() {...}`
    """,
    re.VERBOSE,
)

# Matches a top-level `export default function Name(` line to find the
# start of the component body.
COMPONENT_START_RE = re.compile(
    r"^export\s+default\s+function\s+(\w+)\s*\("
)


def _component_bodies(source: str) -> list[tuple[str, list[str]]]:
    """
    Extract each top-level `export default function Name(...)` body as
    (name, list-of-lines). We rely on the frontend's consistent two-space
    indentation: the body ends at the first line that is `}` at column 0
    following the opening line.
    """
    lines = source.splitlines()
    out: list[tuple[str, list[str]]] = []
    i = 0
    while i < len(lines):
        m = COMPONENT_START_RE.match(lines[i])
        if not m:
            i += 1
            continue
        name = m.group(1)
        body: list[str] = []
        j = i + 1
        while j < len(lines):
            if lines[j].rstrip() == "}":
                break
            body.append(lines[j])
            j += 1
        out.append((name, body))
        i = j + 1
    return out


def _first_early_return_index(body: list[str]) -> int | None:
    for idx, line in enumerate(body):
        # Ignore returns inside nested functions / callbacks / JSX props.
        # Those are indented 4+ spaces beyond the component body baseline,
        # which at this repo's 2-space indent means 6+ leading spaces. We
        # only care about returns at exactly 2 spaces of indent (component
        # body level).
        stripped_leading = len(line) - len(line.lstrip(" "))
        if stripped_leading != 2:
            continue
        if EARLY_RETURN_RE.match(line):
            return idx
    return None


def _hook_call_index_after(body: list[str], start: int) -> int | None:
    for idx in range(start + 1, len(body)):
        line = body[idx]
        stripped_leading = len(line) - len(line.lstrip(" "))
        # Hooks at component-body level live at indent 2. Nested hooks
        # (inside useMemo callbacks etc.) are indent 4+ and are allowed.
        if stripped_leading != 2:
            continue
        if HOOK_CALL_RE.search(line):
            return idx
    return None


# The two files this commit fixes. If we ever regress, this test fails
# with a clear message pointing at the offending line.
REGRESSION_FILES = [
    FRONTEND_COMPONENTS / "settings" / "TrustLadderDetail.tsx",
    FRONTEND_COMPONENTS / "trade" / "AIConfidenceGauge.tsx",
]


@pytest.mark.parametrize("path", REGRESSION_FILES, ids=lambda p: p.name)
def test_no_hook_call_after_early_return(path: Path):
    assert path.exists(), f"Fixture file missing: {path}"
    source = path.read_text(encoding="utf-8")
    components = _component_bodies(source)
    assert components, (
        f"{path.name}: expected at least one `export default function ...` "
        f"component but found none."
    )

    for name, body in components:
        early = _first_early_return_index(body)
        if early is None:
            continue
        hook = _hook_call_index_after(body, early)
        if hook is not None:
            # Attribute line numbers relative to the component body, plus
            # a short excerpt so the failure message points at the bug.
            ret_line = body[early].strip()
            hook_line = body[hook].strip()
            raise AssertionError(
                f"{path.name}::{name}: Rules-of-Hooks violation — hook call "
                f"appears after an early return.\n"
                f"  early return: {ret_line!r}\n"
                f"  later hook:   {hook_line!r}\n"
                f"This will throw React error #310 when the guard flips "
                f"between renders. Move the hook above the early return."
            )
