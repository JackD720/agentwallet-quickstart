"""
AgentWallet SQLite Persistence Layer.

Provides durable storage for wallet state, transactions, and audit logs.
Uses Python's built-in sqlite3 — zero extra dependencies.

Usage:
    from agentwallet import AgentWallet

    # Just add persist=True — everything else is the same
    wallet = AgentWallet("my-agent", budget_cents=5000, persist=True)
    wallet.spend(200, "api-call")

    # Restart your process...
    wallet = AgentWallet("my-agent", persist=True)
    print(wallet.get_balance())  # balance restored!
"""

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

from .core import Transaction, AuditEntry, EventType


# ─────────────────────────────────────────────────────────────────
# SQLite Storage Backend
# ─────────────────────────────────────────────────────────────────

class SQLiteStorage:
    """
    SQLite-backed storage for AgentWallet.

    Stores wallet state, transactions, and audit entries in a single
    .db file. Thread-safe via connection-per-thread pattern.

    Args:
        db_path: Path to SQLite database file.
                 Defaults to "agentwallet.db" in current directory.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or "agentwallet.db"
        self._local = threading.local()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """Get a thread-local database connection."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA foreign_keys=ON")
        return self._local.conn

    def _init_db(self):
        """Create tables if they don't exist."""
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS wallets (
                agent_id TEXT PRIMARY KEY,
                budget_cents INTEGER NOT NULL,
                balance_cents INTEGER NOT NULL,
                max_per_tx_cents INTEGER NOT NULL,
                max_daily_cents INTEGER NOT NULL,
                kill_switch_active INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS transactions (
                tx_id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                amount_cents INTEGER NOT NULL,
                category TEXT NOT NULL,
                approved INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                rule_triggered TEXT,
                verdict TEXT NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY (agent_id) REFERENCES wallets(agent_id)
            );

            CREATE TABLE IF NOT EXISTS audit_entries (
                event_id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                amount_cents INTEGER NOT NULL DEFAULT 0,
                category TEXT NOT NULL DEFAULT '',
                verdict TEXT NOT NULL DEFAULT '',
                rule_id TEXT,
                details TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY (agent_id) REFERENCES wallets(agent_id)
            );

            CREATE INDEX IF NOT EXISTS idx_tx_agent
                ON transactions(agent_id, timestamp);
            CREATE INDEX IF NOT EXISTS idx_audit_agent
                ON audit_entries(agent_id, timestamp);
            CREATE INDEX IF NOT EXISTS idx_audit_type
                ON audit_entries(event_type, timestamp);
        """)
        conn.commit()

    # ─────────────────────────────────────────────────────────────
    # Wallet State
    # ─────────────────────────────────────────────────────────────

    def save_wallet(
        self,
        agent_id: str,
        budget_cents: int,
        balance_cents: int,
        max_per_tx_cents: int,
        max_daily_cents: int,
        kill_switch_active: bool,
        created_at: str,
    ) -> None:
        """Save or update wallet state."""
        conn = self._get_conn()
        conn.execute("""
            INSERT INTO wallets
                (agent_id, budget_cents, balance_cents, max_per_tx_cents,
                 max_daily_cents, kill_switch_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(agent_id) DO UPDATE SET
                balance_cents = excluded.balance_cents,
                kill_switch_active = excluded.kill_switch_active,
                updated_at = excluded.updated_at
        """, (
            agent_id, budget_cents, balance_cents, max_per_tx_cents,
            max_daily_cents, int(kill_switch_active), created_at,
            datetime.utcnow().isoformat() + "Z",
        ))
        conn.commit()

    def load_wallet(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """Load wallet state. Returns None if wallet doesn't exist."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM wallets WHERE agent_id = ?", (agent_id,)
        ).fetchone()
        if row is None:
            return None
        return {
            "agent_id": row["agent_id"],
            "budget_cents": row["budget_cents"],
            "balance_cents": row["balance_cents"],
            "max_per_tx_cents": row["max_per_tx_cents"],
            "max_daily_cents": row["max_daily_cents"],
            "kill_switch_active": bool(row["kill_switch_active"]),
            "created_at": row["created_at"],
        }

    def wallet_exists(self, agent_id: str) -> bool:
        """Check if a wallet exists in the database."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT 1 FROM wallets WHERE agent_id = ?", (agent_id,)
        ).fetchone()
        return row is not None

    # ─────────────────────────────────────────────────────────────
    # Transactions
    # ─────────────────────────────────────────────────────────────

    def save_transaction(self, tx: Transaction) -> None:
        """Save a transaction."""
        conn = self._get_conn()
        conn.execute("""
            INSERT OR REPLACE INTO transactions
                (tx_id, agent_id, amount_cents, category, approved,
                 timestamp, rule_triggered, verdict, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            tx.tx_id, tx.agent_id, tx.amount_cents, tx.category,
            int(tx.approved), tx.timestamp, tx.rule_triggered,
            tx.verdict, json.dumps(tx.metadata),
        ))
        conn.commit()

    def load_transactions(
        self, agent_id: str, limit: int = 1000
    ) -> List[Transaction]:
        """Load transactions for an agent, most recent first."""
        conn = self._get_conn()
        rows = conn.execute("""
            SELECT * FROM transactions
            WHERE agent_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (agent_id, limit)).fetchall()

        txns = []
        for row in reversed(rows):  # reverse back to chronological
            txns.append(Transaction(
                tx_id=row["tx_id"],
                agent_id=row["agent_id"],
                amount_cents=row["amount_cents"],
                category=row["category"],
                approved=bool(row["approved"]),
                timestamp=row["timestamp"],
                rule_triggered=row["rule_triggered"],
                verdict=row["verdict"],
                metadata=json.loads(row["metadata"]),
            ))
        return txns

    # ─────────────────────────────────────────────────────────────
    # Audit Entries
    # ─────────────────────────────────────────────────────────────

    def save_audit_entry(self, entry: AuditEntry) -> None:
        """Save an audit entry."""
        conn = self._get_conn()
        conn.execute("""
            INSERT OR REPLACE INTO audit_entries
                (event_id, timestamp, agent_id, event_type, amount_cents,
                 category, verdict, rule_id, details)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            entry.event_id, entry.timestamp, entry.agent_id,
            entry.event_type, entry.amount_cents, entry.category,
            entry.verdict, entry.rule_id, json.dumps(entry.details),
        ))
        conn.commit()

    def load_audit_entries(
        self,
        agent_id: Optional[str] = None,
        event_type: Optional[str] = None,
        limit: int = 1000,
    ) -> List[AuditEntry]:
        """Load audit entries with optional filters."""
        conn = self._get_conn()
        query = "SELECT * FROM audit_entries WHERE 1=1"
        params: list = []

        if agent_id:
            query += " AND agent_id = ?"
            params.append(agent_id)
        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()

        entries = []
        for row in reversed(rows):
            entries.append(AuditEntry(
                event_id=row["event_id"],
                timestamp=row["timestamp"],
                agent_id=row["agent_id"],
                event_type=row["event_type"],
                amount_cents=row["amount_cents"],
                category=row["category"],
                verdict=row["verdict"],
                rule_id=row["rule_id"],
                details=json.loads(row["details"]),
            ))
        return entries

    # ─────────────────────────────────────────────────────────────
    # Queries
    # ─────────────────────────────────────────────────────────────

    def get_spend_summary(self, agent_id: str) -> Dict[str, Any]:
        """Get aggregate spend data for an agent."""
        conn = self._get_conn()
        row = conn.execute("""
            SELECT
                COUNT(*) as total_txns,
                SUM(CASE WHEN approved = 1 THEN 1 ELSE 0 END) as approved_count,
                SUM(CASE WHEN approved = 0 THEN 1 ELSE 0 END) as denied_count,
                SUM(CASE WHEN approved = 1 THEN amount_cents ELSE 0 END) as total_spent,
                COUNT(DISTINCT category) as unique_categories
            FROM transactions
            WHERE agent_id = ?
        """, (agent_id,)).fetchone()

        return {
            "total_transactions": row["total_txns"],
            "approved_count": row["approved_count"] or 0,
            "denied_count": row["denied_count"] or 0,
            "total_spent_cents": row["total_spent"] or 0,
            "unique_categories": row["unique_categories"],
        }

    def get_spend_by_category(self, agent_id: str) -> List[Dict[str, Any]]:
        """Get spend breakdown by category."""
        conn = self._get_conn()
        rows = conn.execute("""
            SELECT
                category,
                COUNT(*) as tx_count,
                SUM(CASE WHEN approved = 1 THEN amount_cents ELSE 0 END) as total_cents,
                SUM(CASE WHEN approved = 0 THEN 1 ELSE 0 END) as denied_count
            FROM transactions
            WHERE agent_id = ?
            GROUP BY category
            ORDER BY total_cents DESC
        """, (agent_id,)).fetchall()

        return [
            {
                "category": row["category"],
                "transaction_count": row["tx_count"],
                "total_cents": row["total_cents"] or 0,
                "denied_count": row["denied_count"] or 0,
            }
            for row in rows
        ]

    def list_wallets(self) -> List[Dict[str, Any]]:
        """List all wallets in the database."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM wallets ORDER BY created_at"
        ).fetchall()
        return [
            {
                "agent_id": row["agent_id"],
                "budget_cents": row["budget_cents"],
                "balance_cents": row["balance_cents"],
                "kill_switch_active": bool(row["kill_switch_active"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def close(self):
        """Close the database connection."""
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
