"""
AgentWallet — Financial governance infrastructure for AI agents.

Spend controls, rules engine, kill switch, and audit trail.

Quick start:
    from agentwallet import AgentWallet, SpendRule, RuleVerdict

    wallet = AgentWallet("my-agent", budget_cents=5000)
    result = wallet.spend(500, "api-call")

Full docs: https://github.com/JackD720/agentwallet-quickstart
"""

__version__ = "0.1.0"

from .core import (
    AgentWallet,
    GovernanceEngine,
    SpendRule,
    AuditLog,
    Transaction,
    AuditEntry,
    RuleVerdict,
    EventType,
)

from .dashboard import (
    register_wallet,
    unregister_wallet,
    start_dashboard_server,
)

__all__ = [
    # Core
    "AgentWallet",
    "GovernanceEngine",
    "SpendRule",
    "AuditLog",
    "Transaction",
    "AuditEntry",
    "RuleVerdict",
    "EventType",
    # Dashboard
    "register_wallet",
    "unregister_wallet",
    "start_dashboard_server",
]
