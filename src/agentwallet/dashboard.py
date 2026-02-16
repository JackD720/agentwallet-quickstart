"""
AgentWallet Dashboard Server.

Provides a FastAPI-based governance API and serves the monitoring dashboard.
Requires: pip install agentwallet[dashboard]
"""

from datetime import datetime
from typing import Dict, Optional

from .core import AgentWallet, AuditLog, GovernanceEngine


# Global registry for dashboard visibility
_wallets: Dict[str, AgentWallet] = {}


def register_wallet(wallet: AgentWallet) -> None:
    """Register a wallet so the dashboard can monitor it."""
    _wallets[wallet.agent_id] = wallet


def unregister_wallet(agent_id: str) -> None:
    """Remove a wallet from dashboard monitoring."""
    _wallets.pop(agent_id, None)


def get_registered_wallets() -> Dict[str, AgentWallet]:
    """Get all registered wallets."""
    return dict(_wallets)


def start_dashboard_server(port: int = 8100, host: str = "0.0.0.0"):
    """
    Start the governance API server for the dashboard.

    Requires: pip install agentwallet[dashboard]

    Args:
        port: Port to run the API on (default 8100).
        host: Host to bind to (default 0.0.0.0).
    """
    try:
        from fastapi import FastAPI
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import HTMLResponse
        import uvicorn
    except ImportError:
        print("Dashboard requires extra dependencies:")
        print("  pip install agentwallet[dashboard]")
        return

    api = FastAPI(title="AgentWallet Governance API", version="0.1.0")
    api.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @api.get("/health")
    def health():
        return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}

    @api.get("/api/wallets")
    def list_wallets():
        return {"wallets": [w.get_status() for w in _wallets.values()]}

    @api.get("/api/wallets/{agent_id}")
    def get_wallet(agent_id: str):
        w = _wallets.get(agent_id)
        if not w:
            return {"error": "Not found"}
        return w.get_status()

    @api.get("/api/wallets/{agent_id}/balance")
    def get_balance(agent_id: str):
        w = _wallets.get(agent_id)
        if not w:
            return {"error": "Not found"}
        return w.get_balance()

    @api.get("/api/wallets/{agent_id}/transactions")
    def get_transactions(agent_id: str, limit: int = 50):
        w = _wallets.get(agent_id)
        if not w:
            return {"error": "Not found"}
        return {"transactions": w.get_transactions(limit)}

    @api.get("/api/rules")
    def list_rules():
        all_rules = []
        for w in _wallets.values():
            all_rules.extend(w.governance.list_rules())
        return {"rules": all_rules}

    @api.get("/api/audit")
    def get_audit(agent_id: Optional[str] = None, event_type: Optional[str] = None, limit: int = 100):
        all_entries = []
        for w in _wallets.values():
            all_entries.extend(w.audit.get_entries(agent_id=agent_id, event_type=event_type, limit=limit))
        all_entries.sort(key=lambda e: e["timestamp"], reverse=True)
        return {"entries": all_entries[:limit]}

    @api.post("/api/wallets/{agent_id}/kill-switch")
    def kill_switch(agent_id: str):
        w = _wallets.get(agent_id)
        if not w:
            return {"error": "Not found"}
        w.activate_kill_switch("Activated via dashboard")
        return {"status": "activated", "agent_id": agent_id}

    @api.delete("/api/wallets/{agent_id}/kill-switch")
    def deactivate_kill_switch(agent_id: str):
        w = _wallets.get(agent_id)
        if not w:
            return {"error": "Not found"}
        w.deactivate_kill_switch()
        return {"status": "deactivated", "agent_id": agent_id}

    @api.get("/api/dashboard")
    def dashboard_data():
        """Single endpoint for dashboard to poll."""
        wallets = []
        all_transactions = []
        all_audit = []

        for w in _wallets.values():
            wallets.append(w.get_status())
            all_transactions.extend(w.get_transactions(20))
            all_audit.extend(w.audit.get_entries(limit=20))

        all_transactions.sort(key=lambda t: t["timestamp"], reverse=True)
        all_audit.sort(key=lambda e: e["timestamp"], reverse=True)

        return {
            "wallets": wallets,
            "transactions": all_transactions[:50],
            "audit": all_audit[:50],
            "total_agents": len(_wallets),
            "total_budget_cents": sum(w.budget_cents for w in _wallets.values()),
            "total_spent_cents": sum(w.budget_cents - w.balance_cents for w in _wallets.values()),
        }

    print(f"\n  🏦 AgentWallet Governance API → http://{host}:{port}")
    print(f"  📊 API docs → http://localhost:{port}/docs\n")
    uvicorn.run(api, host=host, port=port, log_level="warning")
