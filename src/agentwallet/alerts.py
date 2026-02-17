"""
AgentWallet Webhooks & Alerts.

Pre-built callbacks for notifications when governance events fire.
Plug into wallet.on() with zero config.

Usage:
    from agentwallet import AgentWallet
    from agentwallet.alerts import slack_alert, webhook_alert, budget_alert, console_alert

    wallet = AgentWallet("my-agent", budget_cents=5000, persist=True)

    # Slack notifications on denials
    wallet.on("deny", slack_alert("https://hooks.slack.com/services/T.../B.../xxx"))

    # Webhook POST on every spend
    wallet.on("spend", webhook_alert("https://my-api.com/governance-events"))

    # Alert when budget drops below threshold
    wallet.on("spend", budget_alert(wallet, threshold_pct=80, callback=slack_alert(url)))

    # Pretty console logging
    wallet.on("deny", console_alert())
    wallet.on("kill_switch", console_alert())
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional


# ─────────────────────────────────────────────────────────────────
# Slack Alert
# ─────────────────────────────────────────────────────────────────

def slack_alert(
    webhook_url: str,
    channel: Optional[str] = None,
    username: str = "AgentWallet",
    icon_emoji: str = ":shield:",
    mention: Optional[str] = None,
) -> Callable:
    """
    Create a callback that sends Slack notifications.

    Args:
        webhook_url: Slack incoming webhook URL.
        channel: Override channel (optional).
        username: Bot username shown in Slack.
        icon_emoji: Emoji icon for the bot.
        mention: User/group to mention, e.g. "@channel" or "<@U123>".

    Returns:
        Callback function for wallet.on().

    Usage:
        wallet.on("deny", slack_alert("https://hooks.slack.com/services/..."))
        wallet.on("kill_switch", slack_alert(url, mention="@channel"))
    """
    def _send(data: Dict[str, Any]) -> None:
        try:
            import urllib.request

            # Build message based on event type
            blocks = _build_slack_blocks(data, mention)

            payload = {
                "username": username,
                "icon_emoji": icon_emoji,
                "blocks": blocks,
            }
            if channel:
                payload["channel"] = channel

            # Also include text fallback for notifications
            payload["text"] = _build_fallback_text(data)

            req = urllib.request.Request(
                webhook_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            # Fire async to avoid blocking the agent
            thread = threading.Thread(
                target=lambda: urllib.request.urlopen(req, timeout=5),
                daemon=True,
            )
            thread.start()

        except Exception:
            pass  # Never block the agent on notification failure

    return _send


def _build_fallback_text(data: Dict[str, Any]) -> str:
    """Build plain text fallback for Slack notifications."""
    if "active" in data:
        agent = data.get("agent_id", "unknown")
        if data["active"]:
            return f"🔴 Kill switch ACTIVATED for {agent}: {data.get('reason', '')}"
        else:
            return f"🟢 Kill switch deactivated for {agent}"
    elif "reason" in data and "approved" in data and not data.get("approved", True):
        agent = data.get("agent_id", "unknown")
        amount = data.get("amount_cents", 0)
        reason = data.get("reason", "")
        return f"🚫 Spend denied for {agent}: ${amount/100:.2f} — {reason}"
    elif "approved" in data and data["approved"]:
        agent = data.get("agent_id", "unknown")
        amount = data.get("amount_cents", 0)
        return f"✅ Spend approved for {agent}: ${amount/100:.2f}"
    else:
        return f"AgentWallet event: {json.dumps(data)[:200]}"


def _build_slack_blocks(data: Dict[str, Any], mention: Optional[str] = None) -> List[Dict]:
    """Build Slack Block Kit blocks for rich formatting."""
    blocks = []
    mention_text = f" {mention}" if mention else ""

    if "reason" in data and "approved" in data and not data["approved"]:
        # Denial event
        agent = data.get("agent_id", "unknown")
        amount = data.get("amount_cents", 0)
        reason = data.get("reason", "")
        remaining = data.get("remaining_cents", 0)

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"🚫 *Spend Denied*{mention_text}\n"
                        f"Agent `{agent}` was blocked from spending *${amount/100:.2f}*",
            },
        })
        blocks.append({
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Reason:*\n{reason}"},
                {"type": "mrkdwn", "text": f"*Remaining Budget:*\n${remaining/100:.2f}"},
            ],
        })

    elif "active" in data:
        # Kill switch event
        agent = data.get("agent_id", "unknown")
        reason = data.get("reason", "")

        if data["active"]:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"🔴 *Kill Switch ACTIVATED*{mention_text}\n"
                            f"All spending halted for agent `{agent}`",
                },
            })
            if reason:
                blocks.append({
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*Reason:* {reason}"},
                })
        else:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"🟢 *Kill Switch Deactivated*\n"
                            f"Agent `{agent}` can resume spending",
                },
            })

    elif "approved" in data and data["approved"]:
        # Approval event
        agent = data.get("agent_id", "unknown")
        amount = data.get("amount_cents", 0)
        category = data.get("category", "")
        remaining = data.get("remaining_cents", 0)

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"✅ *Spend Approved*\n"
                        f"Agent `{agent}` spent *${amount/100:.2f}* on `{category}`",
            },
        })
        blocks.append({
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"Remaining: ${remaining/100:.2f}"},
            ],
        })

    else:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"ℹ️ *AgentWallet Event*\n```{json.dumps(data, indent=2)[:500]}```",
            },
        })

    # Timestamp footer
    blocks.append({
        "type": "context",
        "elements": [
            {"type": "mrkdwn", "text": f"⏱ {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"},
        ],
    })

    return blocks


# ─────────────────────────────────────────────────────────────────
# Generic Webhook
# ─────────────────────────────────────────────────────────────────

def webhook_alert(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    include_timestamp: bool = True,
) -> Callable:
    """
    Create a callback that POSTs event data to any webhook URL.

    Args:
        url: Webhook endpoint URL.
        headers: Optional extra headers (e.g., auth tokens).
        include_timestamp: Add UTC timestamp to payload.

    Returns:
        Callback function for wallet.on().

    Usage:
        wallet.on("deny", webhook_alert("https://my-api.com/events"))
        wallet.on("spend", webhook_alert(
            "https://api.example.com/governance",
            headers={"Authorization": "Bearer xxx"},
        ))
    """
    def _send(data: Dict[str, Any]) -> None:
        try:
            import urllib.request

            payload = {**data}
            if include_timestamp:
                payload["_timestamp"] = datetime.utcnow().isoformat() + "Z"
                payload["_source"] = "agentwallet"

            all_headers = {"Content-Type": "application/json"}
            if headers:
                all_headers.update(headers)

            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers=all_headers,
                method="POST",
            )

            thread = threading.Thread(
                target=lambda: urllib.request.urlopen(req, timeout=5),
                daemon=True,
            )
            thread.start()

        except Exception:
            pass

    return _send


# ─────────────────────────────────────────────────────────────────
# Budget Threshold Alert
# ─────────────────────────────────────────────────────────────────

def budget_alert(
    wallet: Any,
    threshold_pct: float = 80,
    callback: Optional[Callable] = None,
) -> Callable:
    """
    Create a callback that fires when budget usage crosses a threshold.

    Only fires once per threshold crossing to avoid spam.

    Args:
        wallet: AgentWallet instance to monitor.
        threshold_pct: Percentage of budget spent to trigger alert (default: 80).
        callback: Inner callback to fire (e.g., slack_alert). If None, prints.

    Returns:
        Callback function for wallet.on().

    Usage:
        wallet.on("spend", budget_alert(wallet, threshold_pct=80,
            callback=slack_alert("https://hooks.slack.com/...")))

        # Multi-threshold
        wallet.on("spend", budget_alert(wallet, threshold_pct=50))
        wallet.on("spend", budget_alert(wallet, threshold_pct=80))
        wallet.on("spend", budget_alert(wallet, threshold_pct=95))
    """
    _fired = {"triggered": False}

    def _check(data: Dict[str, Any]) -> None:
        if _fired["triggered"]:
            return

        spent = wallet.budget_cents - wallet.balance_cents
        pct = (spent / wallet.budget_cents * 100) if wallet.budget_cents > 0 else 0

        if pct >= threshold_pct:
            _fired["triggered"] = True
            alert_data = {
                "agent_id": wallet.agent_id,
                "alert": "budget_threshold",
                "threshold_pct": threshold_pct,
                "current_pct": round(pct, 1),
                "spent_cents": spent,
                "remaining_cents": wallet.balance_cents,
                "budget_cents": wallet.budget_cents,
            }

            if callback:
                callback(alert_data)
            else:
                print(
                    f"⚠️  Budget alert: {wallet.agent_id} has used "
                    f"{pct:.1f}% of ${wallet.budget_cents/100:.2f} budget "
                    f"(${wallet.balance_cents/100:.2f} remaining)"
                )

    return _check


# ─────────────────────────────────────────────────────────────────
# Console Alert (pretty terminal logging)
# ─────────────────────────────────────────────────────────────────

def console_alert(
    verbose: bool = False,
) -> Callable:
    """
    Create a callback that prints formatted alerts to the console.

    Great for development and debugging.

    Args:
        verbose: If True, print full event data.

    Returns:
        Callback function for wallet.on().

    Usage:
        wallet.on("deny", console_alert())
        wallet.on("kill_switch", console_alert())
        wallet.on("spend", console_alert(verbose=True))
    """
    def _print(data: Dict[str, Any]) -> None:
        ts = datetime.utcnow().strftime("%H:%M:%S")

        if "reason" in data and "approved" in data and not data["approved"]:
            agent = data.get("agent_id", "?")
            amount = data.get("amount_cents", 0)
            reason = data.get("reason", "")
            remaining = data.get("remaining_cents", 0)
            print(f"  🚫 [{ts}] DENIED {agent} ${amount/100:.2f} — {reason} (${remaining/100:.2f} left)")

        elif "active" in data:
            agent = data.get("agent_id", "?")
            if data["active"]:
                reason = data.get("reason", "")
                print(f"  🔴 [{ts}] KILL SWITCH ON — {agent}: {reason}")
            else:
                print(f"  🟢 [{ts}] KILL SWITCH OFF — {agent}")

        elif "approved" in data and data["approved"]:
            agent = data.get("agent_id", "?")
            amount = data.get("amount_cents", 0)
            category = data.get("category", "")
            remaining = data.get("remaining_cents", 0)
            print(f"  ✅ [{ts}] APPROVED {agent} ${amount/100:.2f} {category} (${remaining/100:.2f} left)")

        elif "alert" in data:
            agent = data.get("agent_id", "?")
            pct = data.get("current_pct", 0)
            remaining = data.get("remaining_cents", 0)
            print(f"  ⚠️  [{ts}] BUDGET ALERT {agent} at {pct}% — ${remaining/100:.2f} remaining")

        else:
            print(f"  ℹ️  [{ts}] Event: {data}")

        if verbose:
            print(f"       {json.dumps(data, indent=2)}")

    return _print


# ─────────────────────────────────────────────────────────────────
# Multi-alert combiner
# ─────────────────────────────────────────────────────────────────

def multi_alert(*callbacks: Callable) -> Callable:
    """
    Combine multiple callbacks into one.

    Usage:
        wallet.on("deny", multi_alert(
            console_alert(),
            slack_alert("https://hooks.slack.com/..."),
            webhook_alert("https://my-api.com/events"),
        ))
    """
    def _fire(data: Dict[str, Any]) -> None:
        for cb in callbacks:
            try:
                cb(data)
            except Exception:
                pass

    return _fire
