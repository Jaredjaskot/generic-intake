"""
Clio Integration for Generic Intake — Matter + Contact Lookup
=============================================================
Lightweight Clio API client that searches matters by number and returns
the linked client's contact details (name, email, phone).

OAuth tokens are persisted to a file (CLIO_TOKEN_FILE env var) and
auto-refreshed on 401.
"""

import json
import logging
import os

import requests

log = logging.getLogger("generic-intake.clio")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
CLIO_CLIENT_ID = os.getenv("CLIO_CLIENT_ID", "")
CLIO_CLIENT_SECRET = os.getenv("CLIO_CLIENT_SECRET", "")
CLIO_TOKEN_FILE = os.getenv("CLIO_TOKEN_FILE", "clio_tokens.json")

BASE_URL = "https://app.clio.com"

_tokens = {}


# ---------------------------------------------------------------------------
# Token management
# ---------------------------------------------------------------------------
def _load_tokens():
    global _tokens
    if os.path.exists(CLIO_TOKEN_FILE):
        with open(CLIO_TOKEN_FILE, "r") as f:
            _tokens = json.load(f)


def _save_tokens():
    with open(CLIO_TOKEN_FILE, "w") as f:
        json.dump(_tokens, f)


def _refresh_access_token():
    """Refresh the access token using the stored refresh token."""
    global _tokens
    if "refresh_token" not in _tokens:
        raise ValueError("No Clio refresh token available")

    resp = requests.post(
        f"{BASE_URL}/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": _tokens["refresh_token"],
            "client_id": CLIO_CLIENT_ID,
            "client_secret": CLIO_CLIENT_SECRET,
        },
        timeout=10,
    )
    resp.raise_for_status()
    _tokens = resp.json()
    _save_tokens()
    log.info("Clio access token refreshed")


def _api_request(method, endpoint, **kwargs):
    """Authenticated Clio API request with auto-refresh on 401."""
    if not _tokens.get("access_token"):
        _load_tokens()
    if not _tokens.get("access_token"):
        log.error("No Clio access token available")
        return None

    url = f"{BASE_URL}/api/v4/{endpoint}"
    headers = {
        "Authorization": f"Bearer {_tokens['access_token']}",
        "Accept": "application/json",
    }

    resp = requests.request(method, url, headers=headers, timeout=15, **kwargs)

    if resp.status_code == 401:
        try:
            _refresh_access_token()
            headers["Authorization"] = f"Bearer {_tokens['access_token']}"
            resp = requests.request(method, url, headers=headers, timeout=15, **kwargs)
        except Exception as e:
            log.error("Clio token refresh failed: %s", e)
            return None

    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def lookup_matter(matter_number: str) -> dict | None:
    """Look up a Clio matter by display number.

    Returns dict with found, matter_number, name, email, phone, matter_description
    or None if Clio is not configured.
    """
    if not CLIO_CLIENT_ID or not CLIO_CLIENT_SECRET:
        log.warning("Clio credentials not configured")
        return {"found": False, "error": "Clio not configured"}

    try:
        # Search for the matter
        data = _api_request(
            "GET",
            "matters",
            params={
                "query": matter_number,
                "fields": "id,display_number,description,client{id,name}",
                "limit": 5,
            },
        )
        if not data:
            return {"found": False}

        matters = data.get("data", [])
        if not matters:
            return {"found": False}

        # Prefer exact match on display_number
        match = None
        for m in matters:
            if m.get("display_number") == matter_number:
                match = m
                break
        if not match:
            match = matters[0]

        client = match.get("client") or {}
        client_id = client.get("id")

        result = {
            "found": True,
            "matter_number": match.get("display_number", ""),
            "name": client.get("name", ""),
            "email": "",
            "phone": "",
            "matter_description": match.get("description", ""),
        }

        # Fetch contact details if we have a client ID
        if client_id:
            contact = _get_contact(client_id)
            if contact:
                result["name"] = contact.get("name", "") or result["name"]
                result["email"] = contact.get("email", "")
                result["phone"] = contact.get("phone", "")

        return result

    except Exception as e:
        log.error("Clio matter lookup failed: %s", e)
        return {"found": False, "error": "Lookup failed"}


def lookup_contact(email: str) -> dict | None:
    """Look up a Clio contact by email.

    Returns dict with found, name, email, phone or None if not configured.
    """
    if not CLIO_CLIENT_ID or not CLIO_CLIENT_SECRET:
        log.warning("Clio credentials not configured")
        return {"found": False, "error": "Clio not configured"}

    try:
        data = _api_request(
            "GET",
            "contacts",
            params={
                "query": email,
                "type": "Person",
                "fields": "id,name,email_addresses{address},phone_numbers{number}",
                "limit": 5,
            },
        )
        if not data:
            return {"found": False}

        for contact in data.get("data", []):
            for ea in contact.get("email_addresses", []):
                if ea.get("address", "").lower() == email.lower():
                    phone = ""
                    phone_numbers = contact.get("phone_numbers", [])
                    if phone_numbers:
                        phone = phone_numbers[0].get("number", "")
                    return {
                        "found": True,
                        "name": contact.get("name", ""),
                        "email": ea.get("address", ""),
                        "phone": phone,
                    }

        return {"found": False}

    except Exception as e:
        log.error("Clio contact lookup failed: %s", e)
        return {"found": False, "error": "Lookup failed"}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _get_contact(contact_id):
    """Fetch a contact's name, email, and phone by ID."""
    data = _api_request(
        "GET",
        f"contacts/{contact_id}",
        params={"fields": "id,name,email_addresses{address},phone_numbers{number}"},
    )
    if not data:
        return None

    contact = data.get("data", {})
    name = contact.get("name", "")

    email = ""
    email_addresses = contact.get("email_addresses", [])
    if email_addresses:
        email = email_addresses[0].get("address", "")

    phone = ""
    phone_numbers = contact.get("phone_numbers", [])
    if phone_numbers:
        phone = phone_numbers[0].get("number", "")

    return {"name": name, "email": email, "phone": phone}


# Load tokens at import time
_load_tokens()
