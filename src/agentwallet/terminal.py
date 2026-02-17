"""
AgentWallet Terminal Dashboard.

Rich-based live terminal UI for monitoring agent wallets.
Reads directly from SQLite — no server needed.

Usage:
    agentwallet dashboard                     # Live auto-refresh
    agentwallet dashboard --db custom.db      # Custom DB path
    agentwallet dashboard --agent trader-bot  # Filter to one agent
    agentwallet snapshot                      # One-time printout

Requires: pip install agentwallet-gov[cli]
"""

import time
import os
from datetime import datetime, timedelta
from typing import Optional

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.layout import Layout
    from rich.live import Live
    from rich.text import Text
    from rich.columns import Columns
    from rich import box

    HAS_RICH = True
except ImportError:
    HAS_RICH = False

from .storage import SQLiteStorage


def _require_rich():
    if not HAS_RICH:
        raise ImportError(
            "Terminal dashboard requires 'rich'. "
            "Install with: pip install agentwallet-gov[cli]"
        )


def _format_cents(cents: int) -> str:
    """Format cents as dollars."""
    return f"${cents / 100:.2f}"


def _time_ago(timestamp: str) -> str:
    """Convert ISO timestamp to relative time."""
    try:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        now = datetime.utcnow().replace(tzinfo=dt.tzinfo)
        diff = now - dt
        if diff.total_seconds() < 60:
            return f"{int(diff.total_seconds())}s ago"
        elif diff.total_seconds() < 3600:
            return f"{int(diff.total_seconds() / 60)}m ago"
        elif diff.total_seconds() < 86400:
            return f"{int(diff.total_seconds() / 3600)}h ago"
        else:
            return f"{int(diff.total_seconds() / 86400)}d ago"
    except Exception:
        return timestamp[:19]


def _build_wallet_panel(wallet_data: dict, storage: SQLiteStorage) -> Panel:
    """Build a panel for a single wallet."""
    agent_id = wallet_data["agent_id"]
    budget = wallet_data["budget_cents"]
    balance = wallet_data["balance_cents"]
    spent = budget - balance
    kill_switch = wallet_data["kill_switch_active"]

    # Budget bar
    pct = (spent / budget * 100) if budget > 0 else 0
    bar_width = 30
    filled = int(pct / 100 * bar_width)
    if pct > 90:
        bar_color = "red"
    elif pct > 70:
        bar_color = "yellow"
    else:
        bar_color = "green"

    bar = f"[{bar_color}]{'█' * filled}[/{bar_color}]{'░' * (bar_width - filled)}"

    # Kill switch indicator
    ks_text = "[bold red]⚠ KILL SWITCH ACTIVE[/bold red]" if kill_switch else "[green]● Active[/green]"

    # Get summary
    summary = storage.get_spend_summary(agent_id)

    content = Text.from_markup(
        f"  Status: {ks_text}\n"
        f"  Budget:    {_format_cents(budget)}\n"
        f"  Spent:     {_format_cents(spent)}\n"
        f"  Remaining: {_format_cents(balance)}\n"
        f"  Usage:     {bar} {pct:.1f}%\n"
        f"\n"
        f"  Transactions: {summary['total_transactions']}  "
        f"(✓ {summary['approved_count']} | ✗ {summary['denied_count']})\n"
        f"  Categories:   {summary['unique_categories']}"
    )

    return Panel(
        content,
        title=f"[bold cyan]{agent_id}[/bold cyan]",
        border_style="cyan",
        padding=(0, 1),
    )


def _build_transactions_table(storage: SQLiteStorage, agent_id: Optional[str] = None, limit: int = 15) -> Table:
    """Build recent transactions table."""
    table = Table(
        title="Recent Transactions",
        box=box.SIMPLE_HEAVY,
        show_lines=False,
        padding=(0, 1),
    )
    table.add_column("Time", style="dim", width=10)
    table.add_column("Agent", style="cyan", width=14)
    table.add_column("Amount", justify="right", width=10)
    table.add_column("Category", width=18)
    table.add_column("Status", width=10)
    table.add_column("Rule", style="dim", width=16)

    if agent_id:
        txns = list(reversed(storage.load_transactions(agent_id, limit=limit)))
    else:
        wallets = storage.list_wallets()
        all_txns = []
        for w in wallets:
            all_txns.extend(storage.load_transactions(w["agent_id"], limit=limit))
        all_txns.sort(key=lambda t: t.timestamp, reverse=True)
        txns = all_txns[:limit]

    for tx in txns:
        status = "[green]✓ approved[/green]" if tx.approved else "[red]✗ denied[/red]"
        rule = tx.rule_triggered or ""
        table.add_row(
            _time_ago(tx.timestamp),
            tx.agent_id,
            _format_cents(tx.amount_cents),
            tx.category,
            status,
            rule,
        )

    if not txns:
        table.add_row("", "", "", "[dim]No transactions yet[/dim]", "", "")

    return table


def _build_category_table(storage: SQLiteStorage, agent_id: str) -> Table:
    """Build spend-by-category table."""
    table = Table(
        title="Spend by Category",
        box=box.SIMPLE_HEAVY,
        show_lines=False,
        padding=(0, 1),
    )
    table.add_column("Category", style="cyan", width=20)
    table.add_column("Spent", justify="right", width=10)
    table.add_column("Txns", justify="right", width=6)
    table.add_column("Denied", justify="right", width=8)

    categories = storage.get_spend_by_category(agent_id)
    for cat in categories:
        denied_str = f"[red]{cat['denied_count']}[/red]" if cat["denied_count"] > 0 else "0"
        table.add_row(
            cat["category"],
            _format_cents(cat["total_cents"]),
            str(cat["transaction_count"]),
            denied_str,
        )

    if not categories:
        table.add_row("[dim]No data yet[/dim]", "", "", "")

    return table


def _build_audit_table(storage: SQLiteStorage, agent_id: Optional[str] = None, limit: int = 10) -> Table:
    """Build recent audit events table."""
    table = Table(
        title="Audit Log",
        box=box.SIMPLE_HEAVY,
        show_lines=False,
        padding=(0, 1),
    )
    table.add_column("Time", style="dim", width=10)
    table.add_column("Event", width=20)
    table.add_column("Agent", style="cyan", width=14)
    table.add_column("Amount", justify="right", width=10)
    table.add_column("Details", style="dim", width=24)

    entries = storage.load_audit_entries(agent_id=agent_id, limit=limit)
    entries = list(reversed(entries))  # most recent first

    event_colors = {
        "spend_approved": "green",
        "spend_denied": "red",
        "spend_requested": "blue",
        "kill_switch_activated": "bold red",
        "kill_switch_deactivated": "yellow",
        "refund": "magenta",
    }

    for entry in entries:
        color = event_colors.get(entry.event_type, "white")
        event_str = f"[{color}]{entry.event_type}[/{color}]"
        amount_str = _format_cents(entry.amount_cents) if entry.amount_cents > 0 else ""
        details = entry.category or ""
        if entry.rule_id:
            details = f"rule: {entry.rule_id}"

        table.add_row(
            _time_ago(entry.timestamp),
            event_str,
            entry.agent_id,
            amount_str,
            details,
        )

    if not entries:
        table.add_row("", "[dim]No events yet[/dim]", "", "", "")

    return table


def _build_full_dashboard(storage: SQLiteStorage, agent_id: Optional[str] = None) -> Table:
    """Build the complete dashboard as a single renderable."""
    # Get wallets
    wallets = storage.list_wallets()
    if agent_id:
        wallets = [w for w in wallets if w["agent_id"] == agent_id]

    if not wallets:
        return Panel(
            "[yellow]No wallets found in database.[/yellow]\n\n"
            "  Run with persist=True to start tracking:\n"
            "    wallet = AgentWallet('my-agent', persist=True)\n\n"
            "  Or run: agentwallet demo --persist",
            title="[bold cyan]◆ AgentWallet Dashboard[/bold cyan]",
            border_style="cyan",
        )

    # Header
    header = Text.from_markup(
        "\n  [bold cyan]◆ AgentWallet Dashboard[/bold cyan]  "
        f"[dim]db: {storage.db_path} | "
        f"{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC | "
        f"{len(wallets)} wallet{'s' if len(wallets) != 1 else ''}[/dim]\n"
    )

    # Build wallet panels
    wallet_panels = []
    for w in wallets:
        wallet_panels.append(_build_wallet_panel(w, storage))

    # Build tables
    tx_table = _build_transactions_table(storage, agent_id=agent_id, limit=12)

    # Category table for first/filtered agent
    target_agent = agent_id or wallets[0]["agent_id"]
    cat_table = _build_category_table(storage, target_agent)

    audit_table = _build_audit_table(storage, agent_id=agent_id, limit=8)

    # Compose layout
    layout = Table.grid(padding=1)
    layout.add_row(header)

    if len(wallet_panels) <= 3:
        layout.add_row(Columns(wallet_panels, equal=True, expand=True))
    else:
        for i in range(0, len(wallet_panels), 3):
            layout.add_row(Columns(wallet_panels[i : i + 3], equal=True, expand=True))

    layout.add_row(tx_table)

    bottom = Table.grid(expand=True)
    bottom.add_row(cat_table, audit_table)
    layout.add_row(bottom)

    footer = Text.from_markup(
        "  [dim]Press Ctrl+C to exit | Refreshing live[/dim]\n"
    )
    layout.add_row(footer)

    return layout


def render_dashboard(
    db_path: str = "agentwallet.db",
    agent_id: Optional[str] = None,
    refresh: float = 1.0,
) -> None:
    """
    Render a live terminal dashboard that auto-refreshes.

    Args:
        db_path: Path to SQLite database.
        agent_id: Optional agent ID filter.
        refresh: Refresh interval in seconds.
    """
    _require_rich()

    if not os.path.exists(db_path):
        console = Console()
        console.print(f"\n[yellow]Database not found: {db_path}[/yellow]")
        console.print("\nCreate one by running:")
        console.print("  [cyan]agentwallet demo --persist[/cyan]")
        console.print(f"  [cyan]agentwallet dashboard --db agentwallet-demo.db[/cyan]\n")
        return

    storage = SQLiteStorage(db_path=db_path)
    console = Console()

    try:
        with Live(
            _build_full_dashboard(storage, agent_id),
            console=console,
            refresh_per_second=1,
            screen=True,
        ) as live:
            while True:
                time.sleep(refresh)
                live.update(_build_full_dashboard(storage, agent_id))
    except KeyboardInterrupt:
        console.print("\n[dim]Dashboard stopped.[/dim]\n")
    finally:
        storage.close()


def snapshot(
    db_path: str = "agentwallet.db",
    agent_id: Optional[str] = None,
) -> None:
    """
    Print a one-time dashboard snapshot.

    Args:
        db_path: Path to SQLite database.
        agent_id: Optional agent ID filter.
    """
    _require_rich()

    if not os.path.exists(db_path):
        console = Console()
        console.print(f"\n[yellow]Database not found: {db_path}[/yellow]")
        console.print("Run [cyan]agentwallet demo --persist[/cyan] first.\n")
        return

    storage = SQLiteStorage(db_path=db_path)
    console = Console()
    console.print(_build_full_dashboard(storage, agent_id))
    storage.close()
