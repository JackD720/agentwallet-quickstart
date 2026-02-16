"""Tests for SQLite persistence layer."""

import sys
import os
import tempfile
import shutil
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from agentwallet import AgentWallet, SpendRule, RuleVerdict, SQLiteStorage


# Use temp directory for test DBs
TEST_DIR = tempfile.mkdtemp(prefix="agentwallet_test_")


def get_test_db():
    """Get a unique test database path."""
    import uuid
    return os.path.join(TEST_DIR, f"test_{uuid.uuid4().hex[:8]}.db")


def test_persist_basic_spend():
    """Wallet state persists after spend."""
    db = get_test_db()
    wallet = AgentWallet("agent-1", budget_cents=5000, persist=True, db_path=db)
    wallet.spend(500, "api-call")
    wallet.spend(300, "web-search")
    assert wallet.balance_cents == 4200

    # Simulate restart — new wallet instance, same agent_id and db
    wallet2 = AgentWallet("agent-1", persist=True, db_path=db)
    assert wallet2.balance_cents == 4200
    assert wallet2.budget_cents == 5000
    assert len(wallet2.transactions) == 2
    print("✅ test_persist_basic_spend")


def test_persist_kill_switch():
    """Kill switch state persists."""
    db = get_test_db()
    wallet = AgentWallet("agent-1", budget_cents=5000, persist=True, db_path=db)
    wallet.activate_kill_switch("emergency")
    assert wallet.kill_switch_active is True

    # Restart
    wallet2 = AgentWallet("agent-1", persist=True, db_path=db)
    assert wallet2.kill_switch_active is True

    # Spend should be blocked
    result = wallet2.spend(100, "test")
    assert result["approved"] is False
    assert "kill-switch" in result["reason"]

    # Deactivate and restart
    wallet2.deactivate_kill_switch()
    wallet3 = AgentWallet("agent-1", persist=True, db_path=db)
    assert wallet3.kill_switch_active is False
    print("✅ test_persist_kill_switch")


def test_persist_refund():
    """Refunds persist correctly."""
    db = get_test_db()
    wallet = AgentWallet("agent-1", budget_cents=5000, persist=True, db_path=db)
    wallet.spend(1000, "big-call")
    assert wallet.balance_cents == 4000
    wallet.refund(500, "partial refund")
    assert wallet.balance_cents == 4500

    # Restart
    wallet2 = AgentWallet("agent-1", persist=True, db_path=db)
    assert wallet2.balance_cents == 4500
    print("✅ test_persist_refund")


def test_persist_denied_transactions():
    """Denied transactions are also persisted."""
    db = get_test_db()
    wallet = AgentWallet("agent-1", budget_cents=5000, max_per_tx_cents=500, persist=True, db_path=db)
    wallet.spend(200, "small")   # approved
    wallet.spend(600, "big")     # denied — over per-tx limit
    assert len(wallet.transactions) == 2

    # Restart
    wallet2 = AgentWallet("agent-1", persist=True, db_path=db)
    assert len(wallet2.transactions) == 2
    assert wallet2.transactions[0].approved is True
    assert wallet2.transactions[1].approved is False
    print("✅ test_persist_denied_transactions")


def test_persist_audit_log():
    """Audit entries persist across restarts."""
    db = get_test_db()
    wallet = AgentWallet("agent-1", budget_cents=5000, persist=True, db_path=db)
    wallet.spend(200, "call-1")
    wallet.spend(300, "call-2")
    original_audit_count = len(wallet.audit.entries)
    assert original_audit_count > 0

    # Restart
    wallet2 = AgentWallet("agent-1", persist=True, db_path=db)
    assert len(wallet2.audit.entries) > 0
    print("✅ test_persist_audit_log")


def test_persist_multiple_agents():
    """Multiple agents share the same database."""
    db = get_test_db()
    w1 = AgentWallet("agent-A", budget_cents=10000, persist=True, db_path=db)
    w2 = AgentWallet("agent-B", budget_cents=5000, persist=True, db_path=db)

    w1.spend(500, "llm")
    w2.spend(200, "search")

    # Restart both
    w1_restored = AgentWallet("agent-A", persist=True, db_path=db)
    w2_restored = AgentWallet("agent-B", persist=True, db_path=db)

    assert w1_restored.balance_cents == 9500
    assert w2_restored.balance_cents == 4800
    assert len(w1_restored.transactions) == 1
    assert len(w2_restored.transactions) == 1
    print("✅ test_persist_multiple_agents")


def test_persist_custom_rules_still_work():
    """Custom rules work correctly after restore (rules are code, not persisted)."""
    db = get_test_db()
    wallet = AgentWallet("agent-1", budget_cents=5000, persist=True, db_path=db)
    wallet.spend(200, "call-1")

    # Restart and add custom rule
    wallet2 = AgentWallet("agent-1", persist=True, db_path=db)
    wallet2.add_rule(SpendRule(
        rule_id="block-images",
        name="Block image gen",
        condition=lambda ctx: ctx["category"] == "image-gen",
        verdict=RuleVerdict.DENY,
    ))

    result = wallet2.spend(100, "image-gen")
    assert result["approved"] is False
    assert "block-images" in result["reason"]

    result = wallet2.spend(100, "llm-call")
    assert result["approved"] is True
    print("✅ test_persist_custom_rules_still_work")


def test_persist_spend_summary():
    """SQLiteStorage.get_spend_summary works."""
    db = get_test_db()
    wallet = AgentWallet("agent-1", budget_cents=5000, max_per_tx_cents=500, persist=True, db_path=db)
    wallet.spend(200, "llm")
    wallet.spend(300, "llm")
    wallet.spend(600, "big")  # denied

    summary = wallet._storage.get_spend_summary("agent-1")
    assert summary["total_transactions"] == 3
    assert summary["approved_count"] == 2
    assert summary["denied_count"] == 1
    assert summary["total_spent_cents"] == 500
    print("✅ test_persist_spend_summary")


def test_persist_spend_by_category():
    """SQLiteStorage.get_spend_by_category works."""
    db = get_test_db()
    wallet = AgentWallet("agent-1", budget_cents=10000, persist=True, db_path=db)
    wallet.spend(200, "llm-inference")
    wallet.spend(300, "llm-inference")
    wallet.spend(100, "web-search")
    wallet.spend(500, "code-execution")

    categories = wallet._storage.get_spend_by_category("agent-1")
    cat_dict = {c["category"]: c for c in categories}
    assert cat_dict["llm-inference"]["total_cents"] == 500
    assert cat_dict["web-search"]["total_cents"] == 100
    assert cat_dict["code-execution"]["total_cents"] == 500
    print("✅ test_persist_spend_by_category")


def test_persist_list_wallets():
    """SQLiteStorage.list_wallets works."""
    db = get_test_db()
    AgentWallet("alpha", budget_cents=1000, persist=True, db_path=db)
    AgentWallet("beta", budget_cents=2000, persist=True, db_path=db)
    AgentWallet("gamma", budget_cents=3000, persist=True, db_path=db)

    storage = SQLiteStorage(db_path=db)
    wallets = storage.list_wallets()
    agent_ids = [w["agent_id"] for w in wallets]
    assert "alpha" in agent_ids
    assert "beta" in agent_ids
    assert "gamma" in agent_ids
    print("✅ test_persist_list_wallets")


def test_in_memory_still_works():
    """Default in-memory mode is unaffected by persistence changes."""
    wallet = AgentWallet("test-agent", budget_cents=5000)
    assert wallet._storage is None
    result = wallet.spend(500, "api-call")
    assert result["approved"] is True
    assert wallet.balance_cents == 4500
    print("✅ test_in_memory_still_works")


def test_persist_metadata():
    """Transaction metadata persists correctly."""
    db = get_test_db()
    wallet = AgentWallet("agent-1", budget_cents=5000, persist=True, db_path=db)
    wallet.spend(200, "llm", metadata={"model": "gpt-4", "tokens": 1500})

    wallet2 = AgentWallet("agent-1", persist=True, db_path=db)
    assert wallet2.transactions[0].metadata["model"] == "gpt-4"
    assert wallet2.transactions[0].metadata["tokens"] == 1500
    print("✅ test_persist_metadata")


if __name__ == "__main__":
    tests = [
        test_persist_basic_spend,
        test_persist_kill_switch,
        test_persist_refund,
        test_persist_denied_transactions,
        test_persist_audit_log,
        test_persist_multiple_agents,
        test_persist_custom_rules_still_work,
        test_persist_spend_summary,
        test_persist_spend_by_category,
        test_persist_list_wallets,
        test_in_memory_still_works,
        test_persist_metadata,
    ]

    print(f"\nRunning {len(tests)} persistence tests...\n")
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

    # Cleanup
    shutil.rmtree(TEST_DIR, ignore_errors=True)

    print(f"\n{'='*40}")
    print(f"  {passed} passed, {failed} failed")
    print(f"{'='*40}\n")
    sys.exit(1 if failed > 0 else 0)
