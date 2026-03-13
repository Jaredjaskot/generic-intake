"""Slack payment notifications."""

import os
import logging

import requests

log = logging.getLogger("generic-intake.slack")

SLACK_WEBHOOK_URL = os.getenv("SLACK_PAYMENT_WEBHOOK_URL", "")


def notify_payment(session, ct, amount_cents):
    """Send payment notification to Slack."""
    if not SLACK_WEBHOOK_URL:
        log.info("No SLACK_PAYMENT_WEBHOOK_URL configured, skipping")
        return

    amount_str = f"${amount_cents / 100:,.2f}" if amount_cents else "N/A"
    text = (
        f":white_check_mark: *New {ct.display_name} Retainer Signed*\n"
        f"*Client:* {session.name}\n"
        f"*Email:* {session.email}\n"
        f"*Phone:* {session.phone}\n"
        f"*Amount:* {amount_str}\n"
        f"*Language:* {session.lang or 'en'}"
    )

    try:
        requests.post(SLACK_WEBHOOK_URL, json={"text": text}, timeout=10)
    except Exception:
        log.exception("Slack notification failed")
