"""
Tests for SaldoManager and Fuel Gauge calculations.
"""

from datetime import datetime, timezone

import pytest

from src.saldo import SaldoManager, format_minutes_for_display


def test_saldo_tracks_remaining_by_provider():
    manager = SaldoManager(
        starting_balances={
            "openai": 10.0,
            "deepgram": 20.0,
            "anthropic": 5.0,
        },
        baseline_burn_rates={
            "openai": 0.10,
            "deepgram": 0.02,
            "anthropic": 0.05,
        },
    )

    manager.record_cost("openai_gpt_4o_mini", 1.5)
    manager.record_cost("deepgram_interviewer", 0.5)
    manager.record_cost("claude_sonnet", 0.25)

    snapshot = manager.build_snapshot(elapsed_minutes=30)
    providers = snapshot["providers"]

    assert providers["openai"]["remaining_usd"] == 8.5
    assert providers["deepgram"]["remaining_usd"] == 19.5
    assert providers["anthropic"]["remaining_usd"] == 4.75
    assert providers["openai"]["minutes_remaining"] is not None
    assert providers["deepgram"]["minutes_remaining"] is not None
    assert providers["anthropic"]["minutes_remaining"] is not None


def test_saldo_deepgram_live_balance_override(monkeypatch):
    manager = SaldoManager(
        starting_balances={
            "openai": 9.92,
            "deepgram": 188.69,
            "anthropic": 4.74,
        },
        baseline_burn_rates={
            "openai": 0.01,
            "deepgram": 0.005,
            "anthropic": 0.003,
        },
    )
    manager._deepgram_project_id = "proj_123"
    manager._deepgram_api_key = "dg_test"

    def fake_request(url, headers):
        assert "/v1/projects/proj_123/balances" in url
        assert "Authorization" in headers
        return {
            "balances": [
                {"amount": 180.25, "units": "USD"},
                {"amount": 999, "units": "TOKENS"},
            ]
        }

    monkeypatch.setattr(manager, "_request_json", fake_request)
    balance = manager.refresh_deepgram_balance()
    assert balance == 180.25

    snapshot = manager.build_snapshot(elapsed_minutes=15)
    deepgram = snapshot["providers"]["deepgram"]
    assert deepgram["source"] == "live_api"
    assert deepgram["remaining_usd"] == 180.25


def test_format_minutes_for_display():
    assert format_minutes_for_display(None) == "unbounded"
    assert format_minutes_for_display(45) == "45 min"
    assert format_minutes_for_display(180) == "3.0 h"


def test_saldo_openai_live_refresh_from_cost_api(monkeypatch):
    manager = SaldoManager(
        starting_balances={
            "openai": 9.92,
            "deepgram": 188.69,
            "anthropic": 4.74,
        },
        baseline_burn_rates={
            "openai": 0.01,
            "deepgram": 0.005,
            "anthropic": 0.003,
        },
    )
    manager._openai_admin_key = "sk-admin-test"
    manager._openai_live_enabled = True
    manager._baseline_start_utc = datetime(2026, 3, 2, tzinfo=timezone.utc)

    def fake_request(url, headers):
        assert "/v1/organization/costs" in url
        assert "Authorization" in headers
        return {
            "data": [
                {
                    "results": [
                        {"amount": {"value": 1.25}},
                        {"amount": {"value": "0.50"}},
                    ]
                }
            ],
            "has_more": False,
        }

    monkeypatch.setattr(manager, "_request_json", fake_request)
    balance = manager.refresh_openai_balance()

    assert balance == pytest.approx(8.17, abs=1e-6)
    snapshot = manager.build_snapshot(elapsed_minutes=20)
    openai = snapshot["providers"]["openai"]
    assert openai["source"] == "live_api"
    assert openai["remaining_usd"] == pytest.approx(8.17, abs=1e-6)
    assert openai["live_spend_since_baseline_usd"] == pytest.approx(1.75, abs=1e-6)


def test_saldo_anthropic_live_refresh_from_cost_api(monkeypatch):
    manager = SaldoManager(
        starting_balances={
            "openai": 9.92,
            "deepgram": 188.69,
            "anthropic": 4.74,
        },
        baseline_burn_rates={
            "openai": 0.01,
            "deepgram": 0.005,
            "anthropic": 0.003,
        },
    )
    manager._anthropic_admin_key = "sk-ant-admin-test"
    manager._anthropic_live_enabled = True
    manager._baseline_start_utc = datetime(2026, 3, 2, tzinfo=timezone.utc)

    def fake_request(url, headers):
        assert "/v1/organizations/cost_report" in url
        assert "x-api-key" in headers
        return {
            "data": [
                {
                    "results": [
                        {"amount": "0.40"},
                        {"amount": {"value": 0.11}},
                    ]
                }
            ],
            "has_more": False,
        }

    monkeypatch.setattr(manager, "_request_json", fake_request)
    balance = manager.refresh_anthropic_balance()

    assert balance == pytest.approx(4.23, abs=1e-6)
    snapshot = manager.build_snapshot(elapsed_minutes=20)
    anth = snapshot["providers"]["anthropic"]
    assert anth["source"] == "live_api"
    assert anth["remaining_usd"] == pytest.approx(4.23, abs=1e-6)
    assert anth["live_spend_since_baseline_usd"] == pytest.approx(0.51, abs=1e-6)
