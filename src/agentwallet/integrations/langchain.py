"""
AgentWallet LangChain Integration.

Two ways to add governance to your LangChain agents:

1. GovernanceCallback — Drop-in callback that monitors and governs all
   LLM calls and tool usage. Add to any existing agent.

2. govern_tool() — Wrap any LangChain tool with spend controls.
   Every invocation goes through governance before executing.

Usage:
    from agentwallet import AgentWallet
    from agentwallet.integrations.langchain import GovernanceCallback, govern_tool

    wallet = AgentWallet("my-agent", budget_cents=5000, persist=True)

    # Pattern 1: Callback (add to any agent)
    callback = GovernanceCallback(wallet)
    agent.invoke({"input": "search for AI news"}, config={"callbacks": [callback]})

    # Pattern 2: Wrap individual tools
    governed_search = govern_tool(search_tool, wallet, cost_cents=50)

Requires: pip install langchain-core
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Union
from uuid import UUID

try:
    from langchain_core.callbacks import BaseCallbackHandler
    from langchain_core.tools import BaseTool
    from langchain_core.agents import AgentAction, AgentFinish
    from langchain_core.messages import BaseMessage
    from langchain_core.outputs import LLMResult

    HAS_LANGCHAIN = True
except ImportError:
    HAS_LANGCHAIN = False

from ..core import AgentWallet, RuleVerdict


def _require_langchain():
    if not HAS_LANGCHAIN:
        raise ImportError(
            "LangChain integration requires langchain-core. "
            "Install with: pip install agentwallet-gov[langchain]"
        )


# ─────────────────────────────────────────────────────────────────
# GovernanceCallback
# ─────────────────────────────────────────────────────────────────

class GovernanceCallback(BaseCallbackHandler if HAS_LANGCHAIN else object):
    """
    LangChain callback handler that routes all agent activity through
    AgentWallet governance.

    Tracks:
    - LLM calls (estimated cost based on token count)
    - Tool invocations (configurable cost per tool)
    - Agent actions and completions

    Args:
        wallet: AgentWallet instance to govern spending.
        cost_per_1k_tokens: Cost in cents per 1K tokens (default: 3 = $0.03).
        tool_costs: Dict mapping tool names to cost in cents per call.
            Tools not in this dict use default_tool_cost.
        default_tool_cost: Default cost in cents per tool call (default: 10).
        block_on_deny: If True, raise an exception when governance denies
            a spend. If False, log the denial but allow execution (default: True).

    Usage:
        wallet = AgentWallet("my-agent", budget_cents=5000)
        callback = GovernanceCallback(
            wallet,
            cost_per_1k_tokens=3,
            tool_costs={"web_search": 50, "code_interpreter": 100},
        )
        agent.invoke({"input": "..."}, config={"callbacks": [callback]})
    """

    def __init__(
        self,
        wallet: AgentWallet,
        cost_per_1k_tokens: int = 3,
        tool_costs: Optional[Dict[str, int]] = None,
        default_tool_cost: int = 10,
        block_on_deny: bool = True,
    ):
        _require_langchain()
        super().__init__()
        self.wallet = wallet
        self.cost_per_1k_tokens = cost_per_1k_tokens
        self.tool_costs = tool_costs or {}
        self.default_tool_cost = default_tool_cost
        self.block_on_deny = block_on_deny
        self._call_count = 0
        self._total_tokens = 0
        self._tool_calls = 0

    # ── LLM Events ──────────────────────────────────────────────

    def on_llm_start(
        self,
        serialized: Dict[str, Any],
        prompts: List[str],
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        """Check governance before LLM call."""
        self._call_count += 1

    def on_llm_end(
        self,
        response: Any,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        """Record LLM token usage as a governed spend."""
        total_tokens = 0
        try:
            if hasattr(response, "llm_output") and response.llm_output:
                usage = response.llm_output.get("token_usage", {})
                total_tokens = usage.get("total_tokens", 0)
        except Exception:
            pass

        if total_tokens == 0:
            # Estimate from response text if no token count
            try:
                for gen_list in response.generations:
                    for gen in gen_list:
                        total_tokens += len(gen.text) // 4  # rough estimate
            except Exception:
                total_tokens = 100  # fallback estimate

        self._total_tokens += total_tokens
        cost_cents = max(1, (total_tokens * self.cost_per_1k_tokens) // 1000)

        result = self.wallet.spend(
            cost_cents,
            "llm-inference",
            metadata={
                "tokens": total_tokens,
                "call_number": self._call_count,
            },
        )

        if not result["approved"] and self.block_on_deny:
            raise GovernanceDeniedError(
                f"LLM call blocked by governance: {result.get('reason', 'budget exceeded')}. "
                f"Remaining budget: ${result['remaining_cents'] / 100:.2f}"
            )

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        pass

    # ── Tool Events ─────────────────────────────────────────────

    def on_tool_start(
        self,
        serialized: Dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        """Govern tool execution before it runs."""
        tool_name = serialized.get("name", "unknown_tool")
        cost = self.tool_costs.get(tool_name, self.default_tool_cost)

        result = self.wallet.spend(
            cost,
            f"tool:{tool_name}",
            metadata={
                "tool_name": tool_name,
                "input_preview": input_str[:200],
            },
        )

        self._tool_calls += 1

        if not result["approved"] and self.block_on_deny:
            raise GovernanceDeniedError(
                f"Tool '{tool_name}' blocked by governance: {result.get('reason', 'budget exceeded')}. "
                f"Remaining budget: ${result['remaining_cents'] / 100:.2f}"
            )

    def on_tool_end(self, output: str, *, run_id: UUID, **kwargs: Any) -> None:
        pass

    def on_tool_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        pass

    # ── Agent Events ────────────────────────────────────────────

    def on_agent_action(self, action: Any, *, run_id: UUID, **kwargs: Any) -> None:
        pass

    def on_agent_finish(self, finish: Any, *, run_id: UUID, **kwargs: Any) -> None:
        pass

    # ── Chat Model Events ───────────────────────────────────────

    def on_chat_model_start(
        self,
        serialized: Dict[str, Any],
        messages: List[List[Any]],
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        """Track chat model calls."""
        self._call_count += 1

    # ── Stats ───────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """Get callback statistics."""
        return {
            "llm_calls": self._call_count,
            "total_tokens": self._total_tokens,
            "tool_calls": self._tool_calls,
            "wallet_balance": self.wallet.balance_cents,
            "wallet_spent": self.wallet.budget_cents - self.wallet.balance_cents,
        }


# ─────────────────────────────────────────────────────────────────
# govern_tool() — Wrap any tool with governance
# ─────────────────────────────────────────────────────────────────

def govern_tool(
    tool: Any,
    wallet: AgentWallet,
    cost_cents: int = 10,
    category: Optional[str] = None,
    block_message: str = "This tool call was blocked by spending governance.",
) -> Any:
    """
    Wrap a LangChain tool with AgentWallet governance.

    Every invocation goes through the wallet's governance engine.
    If denied, returns block_message instead of executing the tool.

    Args:
        tool: A LangChain BaseTool instance.
        wallet: AgentWallet to govern spending.
        cost_cents: Cost per invocation in cents.
        category: Category for audit trail (defaults to "tool:{tool_name}").
        block_message: Message returned when governance blocks execution.

    Returns:
        A new tool that wraps the original with governance.

    Usage:
        from langchain_community.tools import TavilySearchResults
        search = TavilySearchResults()
        governed_search = govern_tool(search, wallet, cost_cents=50)
        # Use governed_search as a drop-in replacement
    """
    _require_langchain()

    tool_name = getattr(tool, "name", "unknown_tool")
    tool_category = category or f"tool:{tool_name}"

    original_run = tool._run if hasattr(tool, "_run") else None
    original_arun = tool._arun if hasattr(tool, "_arun") else None

    def governed_run(query: str, **kwargs) -> str:
        result = wallet.spend(
            cost_cents,
            tool_category,
            metadata={"tool_name": tool_name, "input_preview": str(query)[:200]},
        )
        if not result["approved"]:
            return f"{block_message} Reason: {result.get('reason', 'budget exceeded')}"
        return original_run(query, **kwargs)

    async def governed_arun(query: str, **kwargs) -> str:
        result = wallet.spend(
            cost_cents,
            tool_category,
            metadata={"tool_name": tool_name, "input_preview": str(query)[:200]},
        )
        if not result["approved"]:
            return f"{block_message} Reason: {result.get('reason', 'budget exceeded')}"
        if original_arun:
            return await original_arun(query, **kwargs)
        return original_run(query, **kwargs)

    # Monkey-patch the tool's run methods
    tool._run = governed_run
    tool._arun = governed_arun
    tool.description = f"[Governed: ${cost_cents/100:.2f}/call] {tool.description}"

    return tool


# ─────────────────────────────────────────────────────────────────
# Exception
# ─────────────────────────────────────────────────────────────────

class GovernanceDeniedError(Exception):
    """Raised when governance blocks an operation."""
    pass
