"""
AgentWallet - Financial governance infrastructure for AI agents.

Spend controls, rules engine, kill switch, and audit trail.
Every financial action an agent takes flows through governance before a dollar moves.

Usage:
    from agentwallet import AgentWallet, SpendRule, RuleVerdict

    wallet = AgentWallet("my-agent", budget_cents=5000)  # $50 budget
    result = wallet.spend(500, "openai-api-call", metadata={"model": "gpt-4"})
    print(result)  # {'approved': True, 'remaining_cents': 4500, ...}

Reference: arXiv:2501.10114 "Infrastructure for AI Agents"
"""

import json
import uuid
import threading
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional, Dict, Any, List, Callable
from pathlib import Path


# ─────────────────────────────────────────────────────────────────
# Data Types
# ─────────────────────────────────────────────────────────────────

class RuleVerdict(Enum):
    """Possible outcomes when a governance rule is triggered."""
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


class EventType(Enum):
    """Types of events recorded in the audit log."""
    SPEND_REQUESTED = "spend_requested"
    SPEND_APPROVED = "spend_approved"
    SPEND_DENIED = "spend_denied"
    SPEND_EXECUTED = "spend_executed"
    RULE_TRIGGERED = "rule_triggered"
    KILL_SWITCH_ON = "kill_switch_activated"
    KILL_SWITCH_OFF = "kill_switch_deactivated"
    REFUND = "refund"


@dataclass
class Transaction:
    """A single financial transaction attempted by an agent."""
    tx_id: str
    agent_id: str
    amount_cents: int
    category: str
    approved: bool
    timestamp: str
    rule_triggered: Optional[str] = None
    verdict: str = "allow"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AuditEntry:
    """A single entry in the immutable audit log."""
    event_id: str
    timestamp: str
    agent_id: str
    event_type: str
    amount_cents: int = 0
    category: str = ""
    verdict: str = ""
    rule_id: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SpendRule:
    """
    A governance rule that controls agent spending.

    Args:
        rule_id: Unique identifier for this rule.
        name: Human-readable name.
        condition: Function(tx_context) -> bool. Return True to TRIGGER the rule.
        verdict: What happens when triggered (DENY, REQUIRE_APPROVAL, ALLOW).
        priority: Higher priority = evaluated first (default 0).
        is_active: Whether this rule is currently active.

    Example:
        SpendRule(
            rule_id="block-expensive",
            name="Block transactions over $10",
            condition=lambda ctx: ctx["amount_cents"] > 1000,
            verdict=RuleVerdict.DENY,
        )
    """
    rule_id: str
    name: str
    condition: Callable[[Dict[str, Any]], bool]
    verdict: RuleVerdict = RuleVerdict.DENY
    priority: int = 0
    is_active: bool = True


# ─────────────────────────────────────────────────────────────────
# Audit Log
# ─────────────────────────────────────────────────────────────────

class AuditLog:
    """
    Append-only audit log for all agent financial actions.
    Writes to a JSONL file for persistence and compliance.
    """

    def __init__(self, log_file: Optional[str] = None):
        self.log_file = log_file or "agentwallet_audit.jsonl"
        self.entries: List[AuditEntry] = []
        self._lock = threading.Lock()

    def log(self, entry: AuditEntry) -> None:
        """Append an entry to the audit log."""
        with self._lock:
            self.entries.append(entry)
            try:
                with open(self.log_file, "a") as f:
                    f.write(json.dumps(asdict(entry), default=str) + "\n")
            except Exception:
                pass  # Don't crash on file write failure

    def create(self, agent_id: str, event_type: EventType, **kwargs) -> AuditEntry:
        """Create and log a new audit entry."""
        entry = AuditEntry(
            event_id=str(uuid.uuid4())[:8],
            timestamp=datetime.utcnow().isoformat() + "Z",
            agent_id=agent_id,
            event_type=event_type.value,
            **kwargs,
        )
        self.log(entry)
        return entry

    def get_entries(
        self,
        agent_id: Optional[str] = None,
        event_type: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query audit entries with optional filters."""
        filtered = self.entries
        if agent_id:
            filtered = [e for e in filtered if e.agent_id == agent_id]
        if event_type:
            filtered = [e for e in filtered if e.event_type == event_type]
        return [asdict(e) for e in filtered[-limit:]]

    def load_from_file(self) -> int:
        """Load existing entries from the JSONL file. Returns count loaded."""
        loaded = 0
        try:
            with open(self.log_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        data = json.loads(line)
                        entry = AuditEntry(**data)
                        self.entries.append(entry)
                        loaded += 1
        except FileNotFoundError:
            pass
        return loaded


# ─────────────────────────────────────────────────────────────────
# Governance Engine
# ─────────────────────────────────────────────────────────────────

class GovernanceEngine:
    """
    The rules engine that sits between AI agent intent and financial execution.
    Every spend request must pass through governance before money moves.
    """

    def __init__(self):
        self.rules: Dict[str, SpendRule] = {}

    def add_rule(self, rule: SpendRule) -> None:
        """Add a governance rule."""
        self.rules[rule.rule_id] = rule

    def remove_rule(self, rule_id: str) -> None:
        """Remove a governance rule by ID."""
        self.rules.pop(rule_id, None)

    def evaluate(self, context: Dict[str, Any]) -> tuple:
        """
        Evaluate all active rules against a transaction context.
        Rules are evaluated in priority order (highest first).
        Returns (verdict: RuleVerdict, triggered_rule_id: str | None).
        """
        sorted_rules = sorted(
            [r for r in self.rules.values() if r.is_active],
            key=lambda r: r.priority,
            reverse=True,
        )

        for rule in sorted_rules:
            try:
                if rule.condition(context):
                    return rule.verdict, rule.rule_id
            except Exception:
                continue

        return RuleVerdict.ALLOW, None

    def list_rules(self) -> List[Dict[str, Any]]:
        """List all rules with their configuration."""
        return [
            {
                "rule_id": r.rule_id,
                "name": r.name,
                "verdict": r.verdict.value,
                "priority": r.priority,
                "active": r.is_active,
            }
            for r in self.rules.values()
        ]


# ─────────────────────────────────────────────────────────────────
# AgentWallet
# ─────────────────────────────────────────────────────────────────

class AgentWallet:
    """
    Financial wallet for an AI agent with built-in governance.

    Every spend request flows through the governance engine before
    money moves. Includes built-in safety rules for kill switch,
    per-transaction limits, daily caps, and balance checks.

    Args:
        agent_id: Unique identifier for this agent.
        budget_cents: Total budget in cents (default $100).
        max_per_tx_cents: Maximum per-transaction in cents (default $20).
        max_daily_cents: Maximum daily spend in cents (default $50).
        audit_log: Optional shared AuditLog instance.
        governance: Optional shared GovernanceEngine instance.
        persist: If True, wallet state survives process restarts (SQLite).
        db_path: Path to SQLite file (default: "agentwallet.db").

    Usage:
        # In-memory (default)
        wallet = AgentWallet("my-agent", budget_cents=5000)

        # With persistence — state survives restarts
        wallet = AgentWallet("my-agent", budget_cents=5000, persist=True)

        wallet.add_rule(SpendRule(
            rule_id="block-gpt4",
            name="Block GPT-4 calls over $5",
            condition=lambda ctx: ctx["amount_cents"] > 500
                and "gpt-4" in ctx.get("metadata", {}).get("model", ""),
            verdict=RuleVerdict.DENY,
        ))

        result = wallet.spend(500, "llm-inference", metadata={"model": "gpt-4"})
    """

    def __init__(
        self,
        agent_id: str,
        budget_cents: int = 10000,
        max_per_tx_cents: int = 2000,
        max_daily_cents: int = 5000,
        audit_log: Optional[AuditLog] = None,
        governance: Optional[GovernanceEngine] = None,
        persist: bool = False,
        db_path: Optional[str] = None,
    ):
        self.agent_id = agent_id
        self.budget_cents = budget_cents
        self.balance_cents = budget_cents
        self.max_per_tx_cents = max_per_tx_cents
        self.max_daily_cents = max_daily_cents

        self.audit = audit_log or AuditLog()
        self.governance = governance or GovernanceEngine()

        self.transactions: List[Transaction] = []
        self.kill_switch_active = False
        self.created_at = datetime.utcnow().isoformat() + "Z"
        self._callbacks: Dict[str, List[Callable]] = {}
        self._storage = None

        # Set up persistence
        if persist:
            from .storage import SQLiteStorage
            self._storage = SQLiteStorage(db_path=db_path)
            self._restore_from_db()

        self._add_default_rules()

    def _restore_from_db(self) -> None:
        """Restore wallet state from SQLite if it exists."""
        if not self._storage:
            return

        saved = self._storage.load_wallet(self.agent_id)
        if saved:
            # Restore persisted state
            self.budget_cents = saved["budget_cents"]
            self.balance_cents = saved["balance_cents"]
            self.max_per_tx_cents = saved["max_per_tx_cents"]
            self.max_daily_cents = saved["max_daily_cents"]
            self.kill_switch_active = saved["kill_switch_active"]
            self.created_at = saved["created_at"]

            # Restore transactions and audit entries into memory
            self.transactions = self._storage.load_transactions(self.agent_id)
            stored_entries = self._storage.load_audit_entries(agent_id=self.agent_id)
            self.audit.entries = stored_entries
        else:
            # First time — save initial state
            self._persist_wallet()

    def _persist_wallet(self) -> None:
        """Save current wallet state to SQLite."""
        if not self._storage:
            return
        self._storage.save_wallet(
            agent_id=self.agent_id,
            budget_cents=self.budget_cents,
            balance_cents=self.balance_cents,
            max_per_tx_cents=self.max_per_tx_cents,
            max_daily_cents=self.max_daily_cents,
            kill_switch_active=self.kill_switch_active,
            created_at=self.created_at,
        )

    def _persist_transaction(self, tx: Transaction) -> None:
        """Save a transaction to SQLite."""
        if not self._storage:
            return
        self._storage.save_transaction(tx)
        # Also persist any new audit entries
        self._persist_new_audit_entries()

    def _persist_new_audit_entries(self) -> None:
        """Persist any audit entries not yet in SQLite."""
        if not self._storage:
            return
        for entry in self.audit.entries:
            self._storage.save_audit_entry(entry)

    def _add_default_rules(self):
        """Built-in safety guardrails."""
        self.governance.add_rule(SpendRule(
            rule_id="kill-switch",
            name="Kill Switch",
            condition=lambda ctx: ctx.get("_kill_switch_active", False),
            verdict=RuleVerdict.DENY,
            priority=1000,
        ))
        self.governance.add_rule(SpendRule(
            rule_id="max-per-tx",
            name=f"Max ${self.max_per_tx_cents / 100:.2f} per transaction",
            condition=lambda ctx: ctx["amount_cents"] > self.max_per_tx_cents,
            verdict=RuleVerdict.DENY,
            priority=900,
        ))
        self.governance.add_rule(SpendRule(
            rule_id="daily-limit",
            name=f"Daily limit ${self.max_daily_cents / 100:.2f}",
            condition=lambda ctx: ctx["_daily_spend"] + ctx["amount_cents"] > self.max_daily_cents,
            verdict=RuleVerdict.DENY,
            priority=800,
        ))
        self.governance.add_rule(SpendRule(
            rule_id="balance-check",
            name="Sufficient balance",
            condition=lambda ctx: ctx["amount_cents"] > ctx["_balance_cents"],
            verdict=RuleVerdict.DENY,
            priority=700,
        ))

    # ─────────────────────────────────────────────────────────────
    # Rules
    # ─────────────────────────────────────────────────────────────

    def add_rule(self, rule: SpendRule) -> None:
        """Add a custom governance rule."""
        self.governance.add_rule(rule)

    def remove_rule(self, rule_id: str) -> None:
        """Remove a governance rule by ID."""
        self.governance.remove_rule(rule_id)

    # ─────────────────────────────────────────────────────────────
    # Callbacks
    # ─────────────────────────────────────────────────────────────

    def on(self, event: str, callback: Callable) -> None:
        """
        Register a callback for governance events.

        Events: "deny", "approve", "kill_switch", "spend"

        Example:
            wallet.on("deny", lambda data: print(f"Blocked: {data}"))
            wallet.on("deny", lambda data: requests.post(webhook_url, json=data))
        """
        if event not in self._callbacks:
            self._callbacks[event] = []
        self._callbacks[event].append(callback)

    def _emit(self, event: str, data: Dict[str, Any]) -> None:
        """Fire all callbacks for an event."""
        for cb in self._callbacks.get(event, []):
            try:
                cb(data)
            except Exception:
                pass

    # ─────────────────────────────────────────────────────────────
    # Core: Spend
    # ─────────────────────────────────────────────────────────────

    def _daily_spend(self) -> int:
        """Calculate total spend in the last 24 hours."""
        cutoff = datetime.utcnow() - timedelta(hours=24)
        return sum(
            t.amount_cents
            for t in self.transactions
            if t.approved and t.timestamp > cutoff.isoformat()
        )

    def spend(
        self,
        amount_cents: int,
        category: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Request a governed spend. The governance engine evaluates all rules
        before allowing the transaction.

        Args:
            amount_cents: Amount to spend in cents.
            category: Category label (e.g., "llm-inference", "api-call").
            metadata: Optional dict of extra context for rule evaluation.

        Returns:
            Dict with 'approved' (bool), 'tx_id', 'remaining_cents', and
            'reason' if denied.
        """
        metadata = metadata or {}
        tx_id = str(uuid.uuid4())[:8]

        context = {
            "tx_id": tx_id,
            "agent_id": self.agent_id,
            "amount_cents": amount_cents,
            "category": category,
            "metadata": metadata,
            "_balance_cents": self.balance_cents,
            "_daily_spend": self._daily_spend(),
            "_kill_switch_active": self.kill_switch_active,
            "_total_transactions": len(self.transactions),
        }

        self.audit.create(
            self.agent_id,
            EventType.SPEND_REQUESTED,
            amount_cents=amount_cents,
            category=category,
            details=metadata,
        )

        verdict, triggered_rule = self.governance.evaluate(context)

        tx = Transaction(
            tx_id=tx_id,
            agent_id=self.agent_id,
            amount_cents=amount_cents,
            category=category,
            approved=(verdict == RuleVerdict.ALLOW),
            timestamp=datetime.utcnow().isoformat() + "Z",
            rule_triggered=triggered_rule,
            verdict=verdict.value,
            metadata=metadata,
        )
        self.transactions.append(tx)

        if verdict == RuleVerdict.ALLOW:
            self.balance_cents -= amount_cents
            self.audit.create(
                self.agent_id,
                EventType.SPEND_APPROVED,
                amount_cents=amount_cents,
                category=category,
                verdict="allow",
            )
            # Persist transaction + updated balance
            self._persist_transaction(tx)
            self._persist_wallet()
            result = {
                "approved": True,
                "tx_id": tx_id,
                "amount_cents": amount_cents,
                "remaining_cents": self.balance_cents,
                "category": category,
            }
            self._emit("approve", result)
            self._emit("spend", result)
            return result
        else:
            self.audit.create(
                self.agent_id,
                EventType.SPEND_DENIED,
                amount_cents=amount_cents,
                category=category,
                verdict=verdict.value,
                rule_id=triggered_rule,
            )
            # Persist denied transaction
            self._persist_transaction(tx)
            result = {
                "approved": False,
                "tx_id": tx_id,
                "reason": f"Blocked by rule: {triggered_rule}",
                "verdict": verdict.value,
                "remaining_cents": self.balance_cents,
            }
            self._emit("deny", result)
            return result

    def refund(self, amount_cents: int, reason: str = "") -> Dict[str, Any]:
        """Refund money back to the wallet."""
        self.balance_cents += amount_cents
        self.audit.create(
            self.agent_id,
            EventType.REFUND,
            amount_cents=amount_cents,
            details={"reason": reason},
        )
        self._persist_wallet()
        return {"refunded_cents": amount_cents, "balance_cents": self.balance_cents}

    # ─────────────────────────────────────────────────────────────
    # Kill Switch
    # ─────────────────────────────────────────────────────────────

    def activate_kill_switch(self, reason: str = "") -> None:
        """Immediately halt all agent spending."""
        self.kill_switch_active = True
        self.audit.create(
            self.agent_id,
            EventType.KILL_SWITCH_ON,
            details={"reason": reason},
        )
        self._persist_wallet()
        self._emit("kill_switch", {"agent_id": self.agent_id, "reason": reason, "active": True})

    def deactivate_kill_switch(self) -> None:
        """Resume agent spending."""
        self.kill_switch_active = False
        self.audit.create(self.agent_id, EventType.KILL_SWITCH_OFF)
        self._persist_wallet()
        self._emit("kill_switch", {"agent_id": self.agent_id, "active": False})

    # ─────────────────────────────────────────────────────────────
    # Getters
    # ─────────────────────────────────────────────────────────────

    def get_balance(self) -> Dict[str, Any]:
        """Get current balance and spend summary."""
        return {
            "agent_id": self.agent_id,
            "balance_cents": self.balance_cents,
            "budget_cents": self.budget_cents,
            "spent_cents": self.budget_cents - self.balance_cents,
            "daily_spend_cents": self._daily_spend(),
        }

    def get_transactions(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent transactions."""
        return [asdict(tx) for tx in self.transactions[-limit:]]

    def get_status(self) -> Dict[str, Any]:
        """Get full wallet status."""
        return {
            "agent_id": self.agent_id,
            "balance_cents": self.balance_cents,
            "budget_cents": self.budget_cents,
            "total_transactions": len(self.transactions),
            "approved_count": len([t for t in self.transactions if t.approved]),
            "denied_count": len([t for t in self.transactions if not t.approved]),
            "daily_spend_cents": self._daily_spend(),
            "kill_switch_active": self.kill_switch_active,
            "rules_count": len(self.governance.rules),
            "created_at": self.created_at,
        }

    def __repr__(self):
        return (
            f"AgentWallet('{self.agent_id}', "
            f"balance=${self.balance_cents / 100:.2f}, "
            f"txns={len(self.transactions)})"
        )
