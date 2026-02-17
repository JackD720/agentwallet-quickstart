# AgentWallet

**Financial governance infrastructure for AI agents.**

Spend controls, rules engine, kill switch, and audit trail — every financial action an agent takes flows through governance before a dollar moves.

```bash
pip install agentwallet-gov
```

```python
from agentwallet import AgentWallet

wallet = AgentWallet("trading-agent", budget_cents=5000, persist=True)
result = wallet.spend(200, "llm-inference", metadata={"model": "gpt-4"})
# {'approved': True, 'tx_id': '...', 'remaining_cents': 4800}
```

---

## Why AgentWallet

AI agents are getting wallets. They're buying API calls, executing trades, spinning up infrastructure. But there's no governance layer between "agent decides to spend" and "money moves."

AgentWallet is that layer. One `pip install`, and every financial action flows through configurable rules, budget controls, and a complete audit trail.

---

## Quick Start

```python
from agentwallet import AgentWallet, SpendRule, RuleVerdict

# Create a governed wallet with $50 budget
wallet = AgentWallet(
    "trading-agent",
    budget_cents=5000,
    max_per_tx_cents=2000,    # $20 max per transaction
    max_daily_cents=3000,     # $30 daily rolling limit
    persist=True,             # survive restarts
)

# Add custom governance rules
wallet.add_rule(SpendRule(
    rule_id="block-expensive-models",
    name="Block GPT-4 calls over $5",
    condition=lambda ctx: ctx["amount_cents"] > 500
        and "gpt-4" in ctx.get("metadata", {}).get("model", ""),
    verdict=RuleVerdict.DENY,
))

# Every spend goes through governance
result = wallet.spend(200, "llm-inference", metadata={"model": "gpt-4"})
# {'approved': True, 'tx_id': '...', 'remaining_cents': 4800}

result = wallet.spend(800, "llm-inference", metadata={"model": "gpt-4"})
# {'approved': False, 'reason': 'Blocked by rule: block-expensive-models'}

# Emergency stop
wallet.activate_kill_switch("suspicious activity detected")
# All subsequent spend() calls return denied
```

---

## Features

### SQLite Persistence

Add `persist=True` and wallet state survives process restarts. Zero config.

```python
# First run
wallet = AgentWallet("my-agent", budget_cents=5000, persist=True)
wallet.spend(200, "api-call")

# ... restart your process ...

# Second run — state restored automatically
wallet = AgentWallet("my-agent", persist=True)
print(wallet.balance_cents)  # 4800 — it remembered
print(len(wallet.transactions))  # 1 — transactions restored too
```

Everything persists: balance, transactions, audit log, kill switch state. Multiple agents share the same database.

```python
# Custom database path
wallet = AgentWallet("agent-1", persist=True, db_path="/data/governance.db")

# Spend analytics
summary = wallet._storage.get_spend_summary("agent-1")
by_category = wallet._storage.get_spend_by_category("agent-1")
all_wallets = wallet._storage.list_wallets()
```

---

### LangChain Integration

Two patterns for adding governance to LangChain agents:

**Pattern 1 — Callback (drop into any agent):**

```python
from agentwallet.integrations.langchain import GovernanceCallback

wallet = AgentWallet("langchain-agent", budget_cents=5000, persist=True)
callback = GovernanceCallback(
    wallet,
    cost_per_1k_tokens=3,
    tool_costs={"web_search": 50, "code_interpreter": 100},
)

# Add to any LangChain agent
agent.invoke({"input": "search for AI news"}, config={"callbacks": [callback]})
```

**Pattern 2 — Wrap individual tools:**

```python
from agentwallet.integrations.langchain import govern_tool

governed_search = govern_tool(search_tool, wallet, cost_cents=50)
# Use as drop-in replacement — governance blocks when budget runs out
```

Install with: `pip install agentwallet-gov[langchain]`

---

### CLI Dashboard

Live terminal dashboard that reads directly from SQLite. No Docker, no browser, no server.

```bash
# Run a demo with persistence
agentwallet demo --persist

# One-time snapshot
agentwallet snapshot --db agentwallet-demo.db

# Live auto-refreshing dashboard
agentwallet dashboard --db agentwallet-demo.db

# Filter to one agent
agentwallet dashboard --db governance.db --agent trading-bot
```

Shows wallet panels with budget bars, transaction history, spend by category, and audit log — all in your terminal.

Install with: `pip install agentwallet-gov[cli]`

---

### Webhook & Slack Alerts

Pre-built callbacks for real-time notifications:

```python
from agentwallet.alerts import slack_alert, budget_alert, console_alert, multi_alert

wallet = AgentWallet("trading-bot", budget_cents=5000, persist=True)

# Slack on denials
wallet.on("deny", slack_alert("https://hooks.slack.com/services/T.../B.../xxx"))

# Kill switch alerts with @channel mention
wallet.on("kill_switch", slack_alert(slack_url, mention="@channel"))

# Console logging for dev
wallet.on("deny", console_alert())

# Budget warnings at multiple thresholds
for pct in [50, 80, 95]:
    wallet.on("spend", budget_alert(wallet, threshold_pct=pct,
        callback=slack_alert(slack_url)))

# Generic webhook to any URL
from agentwallet.alerts import webhook_alert
wallet.on("deny", webhook_alert("https://my-api.com/governance-events",
    headers={"Authorization": "Bearer xxx"}))

# Combine multiple alert channels
wallet.on("deny", multi_alert(
    console_alert(),
    slack_alert(slack_url),
    webhook_alert("https://my-api.com/events"),
))
```

Alerts fire async — they never block the agent.

---

## Built-in Safety Rules

Every wallet ships with four default rules (highest priority first):

| Priority | Rule | Description |
|----------|------|-------------|
| 1000 | **Kill Switch** | Blocks everything when activated |
| 900 | **Max Per Transaction** | Caps individual spend |
| 800 | **Daily Limit** | Caps rolling 24-hour spend |
| 700 | **Balance Check** | Prevents overdraft |

Add your own with `wallet.add_rule()` at any priority level.

---

## Event Callbacks

```python
# Denied transactions
wallet.on("deny", lambda data: print(f"Blocked: {data['reason']}"))

# Approved spend
wallet.on("approve", lambda data: print(f"Spent: ${data['amount_cents']/100:.2f}"))

# All spend attempts (approved + denied)
wallet.on("spend", lambda data: log(data))

# Kill switch toggled
wallet.on("kill_switch", lambda data: alert(data))
```

---

## CLI Reference

```bash
agentwallet version                        # Show version
agentwallet demo                           # Run demo
agentwallet demo --persist                 # Demo with SQLite persistence
agentwallet snapshot --db governance.db    # One-time status printout
agentwallet dashboard --db governance.db   # Live terminal dashboard
agentwallet api --port 8100                # Start REST API server
```

---

## Zero Dependencies

The core SDK has **zero external dependencies**. Just Python 3.9+.

Optional extras:

```bash
pip install agentwallet-gov[langchain]   # LangChain integration
pip install agentwallet-gov[cli]         # Rich terminal dashboard
pip install agentwallet-gov[dashboard]   # FastAPI REST API
```

---

## Architecture

```
Agent Code
    │
    ▼
AgentWallet.spend(amount, category, metadata)
    │
    ▼
GovernanceEngine
    ├── Kill Switch Check
    ├── Per-Transaction Limit
    ├── Daily Spending Limit
    ├── Balance Check
    └── Custom Rules (SpendRule)
    │
    ▼
┌─────────┐    ┌─────────────┐    ┌────────────┐
│ Approved │    │ Audit Trail │    │   Alerts   │
│ / Denied │    │  (SQLite)   │    │(Slack/Hook)│
└─────────┘    └─────────────┘    └────────────┘
```

---

## Links

- **PyPI**: [pypi.org/project/agentwallet-gov](https://pypi.org/project/agentwallet-gov/)
- **Reference**: arXiv:2501.10114 "Infrastructure for AI Agents"

## License

MIT
