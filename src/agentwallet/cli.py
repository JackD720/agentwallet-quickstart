"""
AgentWallet CLI.

Usage:
    agentwallet dashboard                    Live terminal dashboard
    agentwallet dashboard --db data/gov.db   Custom database path
    agentwallet dashboard --agent trader-bot Filter to one agent
    agentwallet snapshot                     One-time status printout
    agentwallet snapshot --db data/gov.db
    agentwallet api                          Start REST API dashboard
    agentwallet demo                         Run a quick demo
    agentwallet demo --persist               Demo with SQLite persistence
    agentwallet version                      Show version
"""

import argparse
import sys


def run_demo(persist=False):
    """Run a quick demo to show AgentWallet in action."""
    from .core import AgentWallet, SpendRule, RuleVerdict

    print("\n  AgentWallet Demo\n")

    kwargs = {}
    if persist:
        kwargs["persist"] = True
        kwargs["db_path"] = "agentwallet-demo.db"
        print("  [SQLite persistence ON -> agentwallet-demo.db]\n")

    wallet = AgentWallet(
        "demo-agent", budget_cents=5000,
        max_per_tx_cents=1500, max_daily_cents=3000,
        **kwargs,
    )
    print(f"  Created: {wallet}")
    print(f"  Budget: ${wallet.budget_cents / 100:.2f}")
    print(f"  Max per tx: ${wallet.max_per_tx_cents / 100:.2f}")
    print(f"  Daily limit: ${wallet.max_daily_cents / 100:.2f}")

    wallet.add_rule(SpendRule(
        rule_id="block-image-gen",
        name="Block image generation",
        condition=lambda ctx: ctx["category"] == "image-generation",
        verdict=RuleVerdict.DENY,
        priority=100,
    ))
    print(f"  Rules: {len(wallet.governance.rules)} active\n")

    calls = [
        (300, "llm-inference", {"model": "gpt-4"}),
        (75, "web-search", {}),
        (500, "llm-inference", {"model": "claude-sonnet"}),
        (2000, "llm-inference", {"model": "expensive"}),
        (800, "image-generation", {}),
        (200, "code-execution", {}),
    ]

    for amount, category, meta in calls:
        result = wallet.spend(amount, category, metadata=meta)
        status = "Approved" if result["approved"] else f"Denied ({result.get('reason', '')})"
        print(f"  ${amount / 100:.2f} {category:20s} -> {status}")

    print(f"\n  Final: {wallet}")
    status = wallet.get_status()
    print(f"  Approved: {status['approved_count']} | Denied: {status['denied_count']}")
    print(f"  Audit entries: {len(wallet.audit.entries)}")

    if persist:
        print(f"\n  Run 'agentwallet dashboard --db agentwallet-demo.db' to see the dashboard!")
        print(f"  Or  'agentwallet snapshot --db agentwallet-demo.db' for a quick view.\n")
    else:
        print()


def run_api_dashboard(port, host):
    """Start the FastAPI dashboard server."""
    try:
        from .dashboard import start_dashboard_server, register_wallet
        from .core import AgentWallet
    except ImportError:
        print("API dashboard requires extra dependencies:")
        print("  pip install agentwallet-gov[dashboard]")
        sys.exit(1)

    demo = AgentWallet("demo-agent", budget_cents=10000)
    demo.spend(500, "llm-inference", metadata={"model": "gpt-4"})
    demo.spend(200, "web-search")
    demo.spend(1500, "code-execution")
    register_wallet(demo)
    start_dashboard_server(port=port, host=host)


def run_terminal_dashboard(db_path, agent_id=None, refresh=1.0):
    """Start the live terminal dashboard."""
    try:
        from .terminal import render_dashboard
    except ImportError:
        print("Terminal dashboard requires 'rich':")
        print("  pip install agentwallet-gov[dashboard-cli]")
        sys.exit(1)
    render_dashboard(db_path=db_path, agent_id=agent_id, refresh=refresh)


def run_snapshot(db_path, agent_id=None):
    """Print a one-time dashboard snapshot."""
    try:
        from .terminal import snapshot
    except ImportError:
        print("Snapshot requires 'rich':")
        print("  pip install agentwallet-gov[dashboard-cli]")
        sys.exit(1)
    snapshot(db_path=db_path, agent_id=agent_id)


def main():
    parser = argparse.ArgumentParser(
        prog="agentwallet",
        description="AgentWallet -- Financial governance for AI agents",
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("version", help="Show version")

    demo_parser = subparsers.add_parser("demo", help="Run a quick demo")
    demo_parser.add_argument("--persist", action="store_true", help="Save to SQLite")

    dash_parser = subparsers.add_parser("dashboard", help="Live terminal dashboard")
    dash_parser.add_argument("--db", type=str, default="agentwallet.db", help="Database path")
    dash_parser.add_argument("--agent", type=str, default=None, help="Filter to agent ID")
    dash_parser.add_argument("--refresh", type=float, default=1.0, help="Refresh seconds")

    snap_parser = subparsers.add_parser("snapshot", help="One-time status printout")
    snap_parser.add_argument("--db", type=str, default="agentwallet.db", help="Database path")
    snap_parser.add_argument("--agent", type=str, default=None, help="Filter to agent ID")

    api_parser = subparsers.add_parser("api", help="Start REST API dashboard")
    api_parser.add_argument("--port", type=int, default=8100, help="Port")
    api_parser.add_argument("--host", type=str, default="0.0.0.0", help="Host")

    args = parser.parse_args()

    if args.command == "version":
        from . import __version__
        print(f"agentwallet {__version__}")
    elif args.command == "demo":
        run_demo(persist=args.persist)
    elif args.command == "dashboard":
        run_terminal_dashboard(db_path=args.db, agent_id=args.agent, refresh=args.refresh)
    elif args.command == "snapshot":
        run_snapshot(db_path=args.db, agent_id=args.agent)
    elif args.command == "api":
        run_api_dashboard(port=args.port, host=args.host)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
