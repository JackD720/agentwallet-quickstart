"""Tests for webhook and Slack alerts."""

import sys
import os
import json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from agentwallet import AgentWallet, SpendRule, RuleVerdict
from agentwallet.alerts import (
    slack_alert,
    webhook_alert,
    budget_alert,
    console_alert,
    multi_alert,
    _build_slack_blocks,
    _build_fallback_text,
)


def test_console_alert_deny():
    """Console alert formats denial correctly."""
    wallet = AgentWallet("test-agent", budget_cents=5000)
    logs = []
    wallet.on("deny", lambda data: logs.append(data))
    wallet.on("deny", console_alert())

    wallet.spend(3000, "big-call")  # denied — over per-tx limit
    assert len(logs) == 1
    assert logs[0]["approved"] is False
    print("✅ test_console_alert_deny")


def test_console_alert_approve():
    """Console alert formats approval correctly."""
    wallet = AgentWallet("test-agent", budget_cents=5000)
    logs = []
    wallet.on("approve", lambda data: logs.append(data))
    wallet.on("approve", console_alert())

    wallet.spend(200, "api-call")
    assert len(logs) == 1
    assert logs[0]["approved"] is True
    print("✅ test_console_alert_approve")


def test_console_alert_kill_switch():
    """Console alert formats kill switch correctly."""
    wallet = AgentWallet("test-agent", budget_cents=5000)
    logs = []
    wallet.on("kill_switch", lambda data: logs.append(data))
    wallet.on("kill_switch", console_alert())

    wallet.activate_kill_switch("runaway spending")
    assert len(logs) == 1
    assert logs[0]["active"] is True

    wallet.deactivate_kill_switch()
    assert len(logs) == 2
    assert logs[1]["active"] is False
    print("✅ test_console_alert_kill_switch")


def test_budget_alert_fires_at_threshold():
    """Budget alert fires when threshold crossed."""
    wallet = AgentWallet("test-agent", budget_cents=1000, max_per_tx_cents=500, max_daily_cents=1000)
    alerts = []

    wallet.on("spend", budget_alert(
        wallet,
        threshold_pct=50,
        callback=lambda data: alerts.append(data),
    ))

    wallet.spend(300, "call-1")  # 30% — no alert
    assert len(alerts) == 0

    wallet.spend(300, "call-2")  # 60% — alert!
    assert len(alerts) == 1
    assert alerts[0]["alert"] == "budget_threshold"
    assert alerts[0]["threshold_pct"] == 50
    assert alerts[0]["current_pct"] >= 50

    wallet.spend(200, "call-3")  # 80% — should NOT fire again
    assert len(alerts) == 1  # still 1, not 2
    print("✅ test_budget_alert_fires_at_threshold")


def test_budget_alert_multiple_thresholds():
    """Multiple budget alerts at different thresholds."""
    wallet = AgentWallet("test-agent", budget_cents=1000, max_per_tx_cents=500, max_daily_cents=1000)
    alerts_50 = []
    alerts_80 = []

    wallet.on("spend", budget_alert(wallet, threshold_pct=50, callback=lambda d: alerts_50.append(d)))
    wallet.on("spend", budget_alert(wallet, threshold_pct=80, callback=lambda d: alerts_80.append(d)))

    wallet.spend(400, "call-1")  # 40%
    assert len(alerts_50) == 0
    assert len(alerts_80) == 0

    wallet.spend(200, "call-2")  # 60%
    assert len(alerts_50) == 1
    assert len(alerts_80) == 0

    wallet.spend(300, "call-3")  # 90%
    assert len(alerts_50) == 1  # already fired
    assert len(alerts_80) == 1  # just fired
    print("✅ test_budget_alert_multiple_thresholds")


def test_multi_alert():
    """Multi-alert combines multiple callbacks."""
    results = []
    cb1 = lambda data: results.append(("cb1", data))
    cb2 = lambda data: results.append(("cb2", data))
    cb3 = lambda data: results.append(("cb3", data))

    combined = multi_alert(cb1, cb2, cb3)
    combined({"test": True})

    assert len(results) == 3
    assert results[0][0] == "cb1"
    assert results[1][0] == "cb2"
    assert results[2][0] == "cb3"
    print("✅ test_multi_alert")


def test_multi_alert_error_isolation():
    """One failing callback doesn't break others."""
    results = []
    cb1 = lambda data: results.append("cb1")
    cb_bad = lambda data: 1/0  # will raise
    cb3 = lambda data: results.append("cb3")

    combined = multi_alert(cb1, cb_bad, cb3)
    combined({"test": True})

    assert len(results) == 2
    assert "cb1" in results
    assert "cb3" in results
    print("✅ test_multi_alert_error_isolation")


def test_slack_blocks_denial():
    """Slack blocks format correctly for denial."""
    data = {
        "approved": False,
        "agent_id": "trader-bot",
        "amount_cents": 5000,
        "reason": "Blocked by rule: max-per-tx",
        "remaining_cents": 7500,
    }
    blocks = _build_slack_blocks(data)
    assert any("Spend Denied" in str(b) for b in blocks)
    assert any("trader-bot" in str(b) for b in blocks)
    assert any("$50.00" in str(b) for b in blocks)
    print("✅ test_slack_blocks_denial")


def test_slack_blocks_kill_switch():
    """Slack blocks format correctly for kill switch."""
    data = {"agent_id": "trader-bot", "active": True, "reason": "runaway"}
    blocks = _build_slack_blocks(data)
    assert any("Kill Switch ACTIVATED" in str(b) for b in blocks)

    data2 = {"agent_id": "trader-bot", "active": False}
    blocks2 = _build_slack_blocks(data2)
    assert any("Deactivated" in str(b) for b in blocks2)
    print("✅ test_slack_blocks_kill_switch")


def test_slack_blocks_approval():
    """Slack blocks format correctly for approval."""
    data = {
        "approved": True,
        "agent_id": "coder-bot",
        "amount_cents": 200,
        "category": "llm-inference",
        "remaining_cents": 4800,
    }
    blocks = _build_slack_blocks(data)
    assert any("Approved" in str(b) for b in blocks)
    assert any("$2.00" in str(b) for b in blocks)
    print("✅ test_slack_blocks_approval")


def test_fallback_text():
    """Fallback text for Slack notifications."""
    deny = {"approved": False, "agent_id": "bot", "amount_cents": 500, "reason": "over budget"}
    assert "denied" in _build_fallback_text(deny).lower()

    kill_on = {"agent_id": "bot", "active": True, "reason": "emergency"}
    assert "kill switch" in _build_fallback_text(kill_on).lower()

    kill_off = {"agent_id": "bot", "active": False}
    assert "deactivated" in _build_fallback_text(kill_off).lower()

    approve = {"approved": True, "agent_id": "bot", "amount_cents": 200}
    assert "approved" in _build_fallback_text(approve).lower()
    print("✅ test_fallback_text")


def test_slack_alert_with_mention():
    """Slack blocks include mention when specified."""
    data = {
        "approved": False,
        "agent_id": "bot",
        "amount_cents": 500,
        "reason": "over budget",
        "remaining_cents": 0,
    }
    blocks = _build_slack_blocks(data, mention="@channel")
    assert any("@channel" in str(b) for b in blocks)
    print("✅ test_slack_alert_with_mention")


def test_webhook_alert_creates_callable():
    """webhook_alert returns a callable."""
    cb = webhook_alert("https://example.com/webhook")
    assert callable(cb)
    print("✅ test_webhook_alert_creates_callable")


def test_full_integration():
    """End-to-end: alerts fire during real wallet operations."""
    wallet = AgentWallet("prod-agent", budget_cents=5000, max_per_tx_cents=2000)

    denials = []
    approvals = []
    budget_warns = []

    wallet.on("deny", lambda d: denials.append(d))
    wallet.on("approve", lambda d: approvals.append(d))
    wallet.on("spend", budget_alert(wallet, threshold_pct=50, callback=lambda d: budget_warns.append(d)))

    wallet.spend(500, "llm")       # approved
    wallet.spend(1000, "llm")      # approved
    wallet.spend(3000, "big")      # denied — per-tx limit
    wallet.spend(1500, "trade")    # approved — crosses 50% threshold

    assert len(approvals) == 3
    assert len(denials) == 1
    assert len(budget_warns) == 1
    assert budget_warns[0]["current_pct"] >= 50
    print("✅ test_full_integration")


if __name__ == "__main__":
    tests = [
        test_console_alert_deny,
        test_console_alert_approve,
        test_console_alert_kill_switch,
        test_budget_alert_fires_at_threshold,
        test_budget_alert_multiple_thresholds,
        test_multi_alert,
        test_multi_alert_error_isolation,
        test_slack_blocks_denial,
        test_slack_blocks_kill_switch,
        test_slack_blocks_approval,
        test_fallback_text,
        test_slack_alert_with_mention,
        test_webhook_alert_creates_callable,
        test_full_integration,
    ]

    print(f"\nRunning {len(tests)} alerts tests...\n")
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"❌ {test.__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print(f"\n{'='*40}")
    print(f"  {passed} passed, {failed} failed")
    print(f"{'='*40}\n")
    sys.exit(1 if failed > 0 else 0)
