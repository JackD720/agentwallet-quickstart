"""
AgentWallet CLI.

Usage:
    agentwallet dashboard          Start the governance dashboard API
    agentwallet dashboard --port 9000
    agentwallet version            Show version
    agentwallet demo               Run a quick demo with sample transactions
"""

import argparse
import sys


def run_demo():
    """Run a quick demo to show AgentWallet in action."""
    from .core import AgentWallet, SpendRule, RuleVerdict

    print("\n  🏦 AgentWallet Demo\n")

    wallet = AgentWallet("demo-agent", budget_cents=5000, max_per_tx_cents=1500, max_daily_cents=3000)
    print(f"  Created: {wallet}")
    print(f"  Budget: ${wallet.budget_cents / 100:.2f}")
    print(f"  Max per tx: ${wallet.max_per_tx_cents / 100:.2f}")
    print(f"  Daily limit: ${wallet.max_daily_cents / 100:.2f}")

    # Add a custom rule
    wallet.add_rule(SpendRule(
        rule_id="block-image-gen",
        name="Block image generation",
        condition=lambda ctx: ctx["category"] == "image-generation",
        verdict=RuleVerdict.DENY,
        priority=100,
    ))
    print(f"  Rules: {len(wallet.governance.rules)} active\n")

    # Run some transactions
    calls = [
        (300, "llm-inference", {"model": "gpt-4"}),
        (75, "web-search", {}),
        (500, "llm-inference", {"model": "claude-sonnet"}),
        (2000, "llm-inference", {"model": "expensive"}),  # over per-tx limit
        (800, "image-generation", {}),  # blocked by custom rule
        (200, "code-execution", {}),
    ]

    for amount, category, meta in calls:
        result = wallet.spend(amount, category, metadata=meta)
        status = "✅ Approved" if result["approved"] else f"❌ Denied ({result.get('reason', '')})"
        print(f"  ${amount / 100:.2f} {category:20s} → {status}")

    print(f"\n  Final: {wallet}")
    status = wallet.get_status()
    print(f"  Approved: {status['approved_count']} | Denied: {status['denied_count']}")
    print(f"  Audit entries: {len(wallet.audit.entries)}\n")


def run_dashboard(port: int, host: str):
    """Start the dashboard server with a demo wallet."""
    try:
        from .dashboard import start_dashboard_server, register_wallet
        from .core import AgentWallet
    except ImportError:
        print("Dashboard requires extra dependencies:")
        print("  pip install agentwallet[dashboard]")
        sys.exit(1)

    # Register a demo wallet so there's something to see
    demo = AgentWallet("demo-agent", budget_cents=10000)
    demo.spend(500, "llm-inference", metadata={"model": "gpt-4"})
    demo.spend(200, "web-search")
    demo.spend(1500, "code-execution")
    register_wallet(demo)

    start_dashboard_server(port=port, host=host)


def main():
    parser = argparse.ArgumentParser(
        prog="agentwallet",
        description="AgentWallet — Financial governance for AI agents",
    )
    subparsers = parser.add_subparsers(dest="command")

    # version
    subparsers.add_parser("version", help="Show version")

    # demo
    subparsers.add_parser("demo", help="Run a quick demo")

    # dashboard
    dash_parser = subparsers.add_parser("dashboard", help="Start governance dashboard API")
    dash_parser.add_argument("--port", type=int, default=8100, help="Port (default: 8100)")
    dash_parser.add_argument("--host", type=str, default="0.0.0.0", help="Host (default: 0.0.0.0)")

    args = parser.parse_args()

    if args.command == "version":
        from . import __version__
        print(f"agentwallet {__version__}")
    elif args.command == "demo":
        run_demo()
    elif args.command == "dashboard":
        run_dashboard(port=args.port, host=args.host)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
