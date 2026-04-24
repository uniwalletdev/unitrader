"""
tests/test_exchanges_list.py — GET /api/exchanges/list contract tests.

Asserts every registered `ExchangeSpec` exposes the metadata the frontend
`ExchangeConnections` component now depends on (Commit 6):

  * `credential_fields` — non-empty list of {name, label, type, ...} dicts
  * `connect_instructions_url` — truthy string
  * `connect_instructions_steps` — non-empty list of strings

Also checks the FEATURE_ETORO_ENABLED flag filters eToro in/out.

Router handlers are invoked directly with a mock `current_user` so no HTTP
stack is required.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

import pytest


def _mock_user() -> SimpleNamespace:
    return SimpleNamespace(id="test-user-listspecs", email="x@t.local")


async def _call_list(feature_etoro: bool) -> dict:
    """Invoke the list_exchanges handler and parse its JSON Response body."""
    from routers.exchanges import list_exchanges
    with patch("routers.exchanges.app_settings") as s:
        s.feature_etoro_enabled = feature_etoro
        resp = await list_exchanges(current_user=_mock_user())
    return json.loads(resp.body)


# ─── Spec completeness ───────────────────────────────────────────────────────

class TestSpecCompleteness:
    """Every registered spec must carry the metadata the wizard/UI needs."""

    EXPECTED_IDS = {"alpaca", "coinbase", "binance", "kraken", "oanda", "etoro"}

    @pytest.mark.asyncio
    async def test_all_registered_specs_have_credential_fields_and_instructions(self):
        payload = await _call_list(feature_etoro=True)
        exchanges = payload["exchanges"]

        ids = {e["id"] for e in exchanges}
        assert ids == self.EXPECTED_IDS, (
            f"Registry mismatch. Expected {self.EXPECTED_IDS}, got {ids}."
        )

        for entry in exchanges:
            xid = entry["id"]

            # credential_fields must be a non-empty list of dicts with name+label+type
            assert isinstance(entry.get("credential_fields"), list), xid
            assert len(entry["credential_fields"]) >= 1, (
                f"{xid} has empty credential_fields — frontend can't render connect form"
            )
            for field in entry["credential_fields"]:
                assert isinstance(field, dict), xid
                assert field.get("name"), f"{xid} field missing name: {field}"
                assert field.get("label"), f"{xid} field missing label: {field}"
                assert field.get("type") in ("text", "password"), (
                    f"{xid} field type invalid: {field.get('type')}"
                )

            # connect_instructions_url must be a truthy string
            assert isinstance(entry.get("connect_instructions_url"), str), xid
            assert entry["connect_instructions_url"].startswith(("http://", "https://")), (
                f"{xid} connect_instructions_url is not an http(s) URL: "
                f"{entry['connect_instructions_url']!r}"
            )

            # connect_instructions_steps must be a non-empty list of non-empty strings
            steps = entry.get("connect_instructions_steps")
            assert isinstance(steps, list), xid
            assert len(steps) >= 1, f"{xid} has no connect_instructions_steps"
            for step in steps:
                assert isinstance(step, str) and step.strip(), (
                    f"{xid} has an empty instruction step: {step!r}"
                )

    @pytest.mark.asyncio
    async def test_coinbase_has_multiline_pem_field(self):
        payload = await _call_list(feature_etoro=True)
        coinbase = next(e for e in payload["exchanges"] if e["id"] == "coinbase")
        pem_field = next(
            (f for f in coinbase["credential_fields"] if f["name"] == "api_secret"),
            None,
        )
        assert pem_field is not None, "coinbase should expose api_secret field"
        assert pem_field.get("multiline") is True, (
            "coinbase api_secret must be multiline so the UI renders a textarea"
        )

    @pytest.mark.asyncio
    async def test_etoro_has_environment_toggle(self):
        payload = await _call_list(feature_etoro=True)
        etoro = next(e for e in payload["exchanges"] if e["id"] == "etoro")
        assert etoro["has_environment_toggle"] is True
        env_opts = {opt[0] for opt in etoro["environment_options"]}
        assert env_opts == {"demo", "real"}


# ─── Feature-flag filter ────────────────────────────────────────────────────

class TestFeatureFlagFilter:

    @pytest.mark.asyncio
    async def test_etoro_hidden_when_flag_off(self):
        payload = await _call_list(feature_etoro=False)
        ids = {e["id"] for e in payload["exchanges"]}
        assert "etoro" not in ids
        # Other exchanges still present
        assert {"alpaca", "coinbase", "binance", "kraken", "oanda"}.issubset(ids)

    @pytest.mark.asyncio
    async def test_etoro_present_when_flag_on(self):
        payload = await _call_list(feature_etoro=True)
        ids = {e["id"] for e in payload["exchanges"]}
        assert "etoro" in ids
