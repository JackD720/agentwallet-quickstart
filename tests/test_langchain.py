"""Tests for LangChain integration."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from agentwallet import AgentWallet, SpendRule, RuleVerdict
from agentwallet.integrations.langchain import (
    GovernanceCallback,
    govern_tool,
    GovernanceDeniedError,
)

# ── Mock LangChain objects for testing without API keys ──────────

from langchain_core.tools import BaseTool
from typing import Optional
from langchain_core.callbacks import CallbackManager


class FakeSearchTool(BaseTool):
    name: str = "web_search"
    description: str = "Search the web for information."

    def _run(self, query: str, **kwargs) -> str:
        return f"Results for: {query}"

    async def _arun(self, query: str, **kwargs) -> str:
        return f"Async results for: {query}"


class FakeCodeTool(BaseTool):
    name: str = "code_interpreter"
    description: str = "Run Python code."

    def _run(self, query: str, **kwargs) -> str:
        return f"Executed: {query}"

    async def _arun(self, query: str, **kwargs) -> str:
        return f"Async executed: {query}"


# ── Tests ────────────────────────────────────────────────────────

def test_governance_callback_init():
    wallet = AgentWallet("test-agent", budget_cents=5000)
    cb = GovernanceCallback(wallet, cost_per_1k_tokens=5, default_tool_cost=25)
    assert cb.wallet is wallet
    assert cb.cost_per_1k_tokens == 5
    assert cb.default_tool_cost == 25
    print("✅ test_governance_callback_init")


def test_governance_callback_stats():
    wallet = AgentWallet("test-agent", budget_cents=5000)
    cb = GovernanceCallback(wallet)
    stats = cb.get_stats()
    assert stats["llm_calls"] == 0
    assert stats["tool_calls"] == 0
    assert stats["wallet_balance"] == 5000
    print("✅ test_governance_callback_stats")


def test_govern_tool_approved():
    wallet = AgentWallet("test-agent", budget_cents=5000)
    tool = FakeSearchTool()
    governed = govern_tool(tool, wallet, cost_cents=50)

    result = governed._run("AI news")
    assert "Results for: AI news" in result
    assert wallet.balance_cents == 4950
    print("✅ test_govern_tool_approved")


def test_govern_tool_denied_over_budget():
    wallet = AgentWallet("test-agent", budget_cents=100)
    tool = FakeSearchTool()
    governed = govern_tool(tool, wallet, cost_cents=200)

    result = governed._run("AI news")
    assert "blocked" in result.lower()
    assert wallet.balance_cents == 100  # unchanged
    print("✅ test_govern_tool_denied_over_budget")


def test_govern_tool_denied_by_kill_switch():
    wallet = AgentWallet("test-agent", budget_cents=5000)
    wallet.activate_kill_switch("emergency stop")
    tool = FakeSearchTool()
    governed = govern_tool(tool, wallet, cost_cents=10)

    result = governed._run("AI news")
    assert "blocked" in result.lower()
    assert "kill-switch" in result.lower()
    print("✅ test_govern_tool_denied_by_kill_switch")


def test_govern_tool_denied_by_custom_rule():
    wallet = AgentWallet("test-agent", budget_cents=5000)
    wallet.add_rule(SpendRule(
        rule_id="block-search",
        name="Block web search",
        condition=lambda ctx: "web_search" in ctx.get("metadata", {}).get("tool_name", ""),
        verdict=RuleVerdict.DENY,
        priority=100,
    ))
    tool = FakeSearchTool()
    governed = govern_tool(tool, wallet, cost_cents=10)

    result = governed._run("AI news")
    assert "blocked" in result.lower()
    assert "block-search" in result.lower()

    # Code tool should still work
    code_tool = FakeCodeTool()
    governed_code = govern_tool(code_tool, wallet, cost_cents=10)
    result = governed_code._run("print('hi')")
    assert "Executed" in result
    print("✅ test_govern_tool_denied_by_custom_rule")


def test_govern_tool_multiple_calls_drain_budget():
    wallet = AgentWallet("test-agent", budget_cents=500, max_per_tx_cents=200, max_daily_cents=500)
    tool = FakeSearchTool()
    governed = govern_tool(tool, wallet, cost_cents=100)

    # 5 calls = 500 cents = exact budget
    for i in range(5):
        result = governed._run(f"query {i}")
        assert "Results for" in result

    # 6th call should be denied
    result = governed._run("one too many")
    assert "blocked" in result.lower()
    assert wallet.balance_cents == 0
    print("✅ test_govern_tool_multiple_calls_drain_budget")


def test_govern_tool_description_updated():
    wallet = AgentWallet("test-agent", budget_cents=5000)
    tool = FakeSearchTool()
    assert "Governed" not in tool.description

    govern_tool(tool, wallet, cost_cents=50)
    assert "Governed" in tool.description
    assert "$0.50" in tool.description
    print("✅ test_govern_tool_description_updated")


def test_govern_tool_audit_trail():
    wallet = AgentWallet("test-agent", budget_cents=5000)
    tool = FakeSearchTool()
    governed = govern_tool(tool, wallet, cost_cents=50)

    governed._run("AI news")
    governed._run("ML papers")

    txns = wallet.get_transactions()
    assert len(txns) == 2
    assert txns[0]["category"] == "tool:web_search"
    assert txns[1]["category"] == "tool:web_search"
    assert all(t["approved"] for t in txns)
    print("✅ test_govern_tool_audit_trail")


def test_govern_tool_with_persistence():
    """Governed tool calls persist to SQLite."""
    import tempfile
    db = os.path.join(tempfile.mkdtemp(), "test.db")

    wallet = AgentWallet("test-agent", budget_cents=5000, persist=True, db_path=db)
    tool = FakeSearchTool()
    governed = govern_tool(tool, wallet, cost_cents=50)
    governed._run("AI news")

    # Restart
    wallet2 = AgentWallet("test-agent", persist=True, db_path=db)
    assert wallet2.balance_cents == 4950
    assert len(wallet2.transactions) == 1
    print("✅ test_govern_tool_with_persistence")


def test_callback_tool_costs():
    wallet = AgentWallet("test-agent", budget_cents=5000)
    cb = GovernanceCallback(
        wallet,
        tool_costs={"web_search": 100, "code_interpreter": 200},
        default_tool_cost=50,
    )
    assert cb.tool_costs["web_search"] == 100
    assert cb.tool_costs["code_interpreter"] == 200
    assert cb.default_tool_cost == 50
    print("✅ test_callback_tool_costs")


if __name__ == "__main__":
    tests = [
        test_governance_callback_init,
        test_governance_callback_stats,
        test_govern_tool_approved,
        test_govern_tool_denied_over_budget,
        test_govern_tool_denied_by_kill_switch,
        test_govern_tool_denied_by_custom_rule,
        test_govern_tool_multiple_calls_drain_budget,
        test_govern_tool_description_updated,
        test_govern_tool_audit_trail,
        test_govern_tool_with_persistence,
        test_callback_tool_costs,
    ]

    print(f"\nRunning {len(tests)} LangChain integration tests...\n")
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
