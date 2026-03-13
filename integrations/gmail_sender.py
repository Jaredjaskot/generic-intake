"""Send emails via Gmail API over HTTPS (port 443).

DigitalOcean blocks SMTP ports (25/465/587), so we use the Gmail API
REST endpoint instead. Requires OAuth2 credentials (not app passwords).

Env vars:
    GMAIL_CLIENT_ID      — Google OAuth2 client ID
    GMAIL_CLIENT_SECRET   — Google OAuth2 client secret
    GMAIL_REFRESH_TOKEN   — OAuth2 refresh token for the sending account
    SMTP_EMAIL            — Sender email (fallback for From header)
"""

import base64
import logging
import os
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

log = logging.getLogger("generic-intake.gmail")

GMAIL_CLIENT_ID = os.getenv("GMAIL_CLIENT_ID", "")
GMAIL_CLIENT_SECRET = os.getenv("GMAIL_CLIENT_SECRET", "")
GMAIL_REFRESH_TOKEN = os.getenv("GMAIL_REFRESH_TOKEN", "")
SENDER_EMAIL = os.getenv("SMTP_EMAIL", "info@jaskot.law")

TOKEN_URL = "https://oauth2.googleapis.com/token"
SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"


def _get_access_token():
    """Exchange refresh token for a short-lived access token."""
    resp = requests.post(TOKEN_URL, data={
        "client_id": GMAIL_CLIENT_ID,
        "client_secret": GMAIL_CLIENT_SECRET,
        "refresh_token": GMAIL_REFRESH_TOKEN,
        "grant_type": "refresh_token",
    }, timeout=10)
    resp.raise_for_status()
    return resp.json()["access_token"]


def send_email(to_email, subject, body, attachments=None, bcc=None):
    """Send an email via Gmail API.

    Args:
        to_email: Recipient email address
        subject: Email subject
        body: Plain text body
        attachments: List of (filename, bytes) tuples
        bcc: BCC email address
    """
    if not GMAIL_CLIENT_ID or not GMAIL_CLIENT_SECRET or not GMAIL_REFRESH_TOKEN:
        log.warning("Gmail API credentials not configured, skipping email")
        return False

    msg = MIMEMultipart()
    msg["From"] = SENDER_EMAIL
    msg["To"] = to_email
    msg["Subject"] = subject
    if bcc:
        msg["Bcc"] = bcc
    msg.attach(MIMEText(body, "plain", "utf-8"))

    for filename, file_bytes in (attachments or []):
        attachment = MIMEApplication(file_bytes, _subtype="pdf")
        attachment.add_header("Content-Disposition", "attachment", filename=filename)
        msg.attach(attachment)

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")

    access_token = _get_access_token()
    resp = requests.post(
        SEND_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        json={"raw": raw},
        timeout=30,
    )
    resp.raise_for_status()
    log.info("Email sent via Gmail API to %s", to_email)
    return True
