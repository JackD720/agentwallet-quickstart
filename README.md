# AgentWallet

**Financial governance infrastructure for AI agents.**

Spend controls, rules engine, kill switch, and audit trail — every financial action an agent takes flows through governance before a dollar moves.

## Install

```bash
pip install agentwallet
```

## Quick Start

```python
from agentwallet import AgentWallet, SpendRule, RuleVerdict

# Create a governed wallet
wallet = AgentWallet("trading-agent", budget_cents=5000)  # $50 budget

# Add custom governance rules
wallet.add_rule(SpendRule(
    rule_id="block-expensive-models",
    name="Block calls over $5",
    condition=lambda ctx: ctx["amount_cents"] > 500
        and "gpt-4" in ctx.get("metadata", {}).get("model", ""),
    verdict=RuleVerdict.DENY,
))

# Every spend goes through governance
result = wallet.spend(200, "llm-inference", metadata={"model": "gpt-4"})
# {'approved': True, 'tx_id': '...', 'remaining_cents': 4800}

result = wallet.spend(800, "llm-inference", metadata={"model": "gpt-4"})
# {'approved': False, 'reason': 'Blocked by rule: block-expensive-models'}
```

## What's Included

- **AgentWallet** — Per-agent wallets with configurable budgets
- **GovernanceEngine** — Rules engine that evaluates every transaction
- **SpendRule** — Custom rules with priority-based evaluation
- **Kill Switch** — Instant shutdown of all agent spending
- **AuditLog** — Append-only JSONL audit trail for compliance
- **Event Callbacks** — `wallet.on("deny", callback)` for webhooks/alerts
- **Dashboard API** — FastAPI server for real-time monitoring
- **CLI** — `agentwallet demo` and `agentwallet dashboard`

## Built-in Safety Rules

Every wallet ships with four default rules (highest priority first):

1. **Kill Switch** (priority 1000) — blocks everything when activated
2. **Max Per Transaction** (priority 900) — caps individual spend
3. **Daily Limit** (priority 800) — caps rolling 24-hour spend
4. **Balance Check** (priority 700) — prevents overdraft

## Event Callbacks

Get notified when governance events fire:

```python
import requests

# Webhook on denied transactions
wallet.on("deny", lambda data: requests.post(
    "https://hooks.slack.com/your-webhook",
    json={"text": f"🚫 Agent blocked: {data['reason']}"}
))

# Log all approved spend
wallet.on("approve", lambda data: print(f"✅ ${data['amount_cents']/100:.2f} approved"))

# Kill switch alerts
wallet.on("kill_switch", lambda data: print(f"🛑 Kill switch: {data}"))
```

## Dashboard

```bash
pip install agentwallet[dashboard]
agentwallet dashboard
```

Or programmatically:

```python
from agentwallet import AgentWallet, register_wallet, start_dashboard_server

wallet = AgentWallet("my-agent", budget_cents=10000)
register_wallet(wallet)
start_dashboard_server(port=8100)  # API at http://localhost:8100/docs
```

## CLI

```bash
agentwallet demo        # Run a quick demo with sample transactions
agentwallet dashboard   # Start the governance API server
agentwallet version     # Show version
```

## Zero Dependencies

The core SDK has **zero external dependencies**. Just Python 3.9+. The dashboard server optionally uses FastAPI + uvicorn.

## Links

- **Quickstart Repo**: [github.com/JackD720/agentwallet-quickstart](https://github.com/JackD720/agentwallet-quickstart)
- **Examples**: 3 working examples (simple agent, LangChain, CrewAI)
- **Reference**: arXiv:2501.10114 "Infrastructure for AI Agents"

## License

MIT
