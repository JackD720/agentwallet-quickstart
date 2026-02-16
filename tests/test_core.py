"""Tests for agentwallet package."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from agentwallet import (
    AgentWallet, SpendRule, RuleVerdict, GovernanceEngine,
    AuditLog, register_wallet, EventType,
)


def test_basic_spend():
    wallet = AgentWallet("test-agent", budget_cents=5000)
    result = wallet.spend(500, "api-call")
    assert result["approved"] is True
    assert result["remaining_cents"] == 4500
    print("✅ test_basic_spend")


def test_over_budget():
    wallet = AgentWallet("test-agent", budget_cents=1000)
    result = wallet.spend(1500, "api-call")
    assert result["approved"] is False
    assert "balance-check" in result["reason"]
    print("✅ test_over_budget")


def test_per_tx_limit():
    wallet = AgentWallet("test-agent", budget_cents=10000, max_per_tx_cents=500)
    result = wallet.spend(600, "api-call")
    assert result["approved"] is False
    assert "max-per-tx" in result["reason"]
    print("✅ test_per_tx_limit")


def test_daily_limit():
    wallet = AgentWallet("test-agent", budget_cents=100000, max_per_tx_cents=50000, max_daily_cents=1000)
    wallet.spend(600, "call-1")
    wallet.spend(300, "call-2")
    result = wallet.spend(200, "call-3")  # would exceed daily 1000
    assert result["approved"] is False
    assert "daily-limit" in result["reason"]
    print("✅ test_daily_limit")


def test_kill_switch():
    wallet = AgentWallet("test-agent", budget_cents=5000)
    wallet.activate_kill_switch("test reason")
    result = wallet.spend(100, "api-call")
    assert result["approved"] is False
    assert "kill-switch" in result["reason"]

    wallet.deactivate_kill_switch()
    result = wallet.spend(100, "api-call")
    assert result["approved"] is True
    print("✅ test_kill_switch")


def test_custom_rule():
    wallet = AgentWallet("test-agent", budget_cents=5000)
    wallet.add_rule(SpendRule(
        rule_id="block-images",
        name="Block image generation",
        condition=lambda ctx: ctx["category"] == "image-gen",
        verdict=RuleVerdict.DENY,
        priority=100,
    ))
    result = wallet.spend(100, "image-gen")
    assert result["approved"] is False
    assert "block-images" in result["reason"]

    result = wallet.spend(100, "llm-call")
    assert result["approved"] is True
    print("✅ test_custom_rule")


def test_refund():
    wallet = AgentWallet("test-agent", budget_cents=5000)
    wallet.spend(1000, "api-call")
    assert wallet.balance_cents == 4000
    wallet.refund(500, "partial refund")
    assert wallet.balance_cents == 4500
    print("✅ test_refund")


def test_audit_log():
    wallet = AgentWallet("test-agent", budget_cents=5000)
    wallet.spend(100, "call-1")
    wallet.spend(200, "call-2")
    entries = wallet.audit.get_entries(agent_id="test-agent")
    assert len(entries) > 0
    assert all(e["agent_id"] == "test-agent" for e in entries)
    print("✅ test_audit_log")


def test_audit_filter_by_event_type():
    wallet = AgentWallet("test-agent", budget_cents=5000)
    wallet.spend(100, "call-1")
    denied = wallet.audit.get_entries(event_type="spend_denied")
    approved = wallet.audit.get_entries(event_type="spend_approved")
    # At least one approved (the 100 cent spend)
    assert len(approved) >= 1
    print("✅ test_audit_filter_by_event_type")


def test_callbacks():
    denied_events = []
    approved_events = []

    wallet = AgentWallet("test-agent", budget_cents=5000, max_per_tx_cents=500)
    wallet.on("deny", lambda data: denied_events.append(data))
    wallet.on("approve", lambda data: approved_events.append(data))

    wallet.spend(200, "small-call")
    wallet.spend(600, "big-call")  # over limit

    assert len(approved_events) == 1
    assert len(denied_events) == 1
    assert approved_events[0]["approved"] is True
    assert denied_events[0]["approved"] is False
    print("✅ test_callbacks")


def test_get_status():
    wallet = AgentWallet("test-agent", budget_cents=5000)
    wallet.spend(100, "call-1")
    wallet.spend(200, "call-2")
    status = wallet.get_status()
    assert status["agent_id"] == "test-agent"
    assert status["total_transactions"] == 2
    assert status["approved_count"] == 2
    assert status["balance_cents"] == 4700
    print("✅ test_get_status")


def test_metadata_in_rules():
    wallet = AgentWallet("test-agent", budget_cents=10000)
    wallet.add_rule(SpendRule(
        rule_id="block-gpt4",
        name="Block GPT-4",
        condition=lambda ctx: ctx.get("metadata", {}).get("model") == "gpt-4",
        verdict=RuleVerdict.DENY,
        priority=100,
    ))
    result = wallet.spend(100, "llm", metadata={"model": "gpt-4"})
    assert result["approved"] is False

    result = wallet.spend(100, "llm", metadata={"model": "gpt-3.5"})
    assert result["approved"] is True
    print("✅ test_metadata_in_rules")


def test_repr():
    wallet = AgentWallet("test-agent", budget_cents=5000)
    r = repr(wallet)
    assert "test-agent" in r
    assert "$50.00" in r
    print("✅ test_repr")


def test_version():
    from agentwallet import __version__
    assert __version__ == "0.1.0"
    print("✅ test_version")


if __name__ == "__main__":
    tests = [
        test_basic_spend,
        test_over_budget,
        test_per_tx_limit,
        test_daily_limit,
        test_kill_switch,
        test_custom_rule,
        test_refund,
        test_audit_log,
        test_audit_filter_by_event_type,
        test_callbacks,
        test_get_status,
        test_metadata_in_rules,
        test_repr,
        test_version,
    ]

    print(f"\nRunning {len(tests)} tests...\n")
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"❌ {test.__name__}: {e}")
            failed += 1

    print(f"\n{'='*40}")
    print(f"  {passed} passed, {failed} failed")
    print(f"{'='*40}\n")
    sys.exit(1 if failed > 0 else 0)
