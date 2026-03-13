"""GHL (GoHighLevel) integration — parameterized by CaseType."""

import os
import logging
import functools

import requests

log = logging.getLogger("generic-intake.ghl")

GHL_API_KEY = os.getenv("GHL_API_KEY", "")
GHL_LOCATION_ID = os.getenv("GHL_LOCATION_ID", "oBw0k5jJ8btKciEWwGp8")
GHL_PIPELINE_ID = os.getenv("GHL_PIPELINE_ID", "DyRIxzCkLcyo9tzJHeaK")
GHL_BASE = "https://services.leadconnectorhq.com"


def ghl_safe(fn):
    """Decorator — swallow GHL errors so they never block the intake funnel."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:
            log.exception("GHL call %s failed (non-fatal)", fn.__name__)
            return None
    return wrapper


def _headers():
    return {
        "Authorization": f"Bearer {GHL_API_KEY}",
        "Content-Type": "application/json",
        "Version": "2021-07-28",
    }


@ghl_safe
def find_or_create_contact(name, email, phone):
    """Find existing contact by email/phone, or create new one."""
    headers = _headers()

    # Search by email
    if email:
        r = requests.post(
            f"{GHL_BASE}/contacts/search/duplicate",
            headers=headers,
            json={"locationId": GHL_LOCATION_ID, "email": email},
        )
        if r.ok and r.json().get("contact"):
            return r.json()["contact"]["id"]

    # Search by phone
    if phone:
        r = requests.post(
            f"{GHL_BASE}/contacts/search/duplicate",
            headers=headers,
            json={"locationId": GHL_LOCATION_ID, "phone": phone},
        )
        if r.ok and r.json().get("contact"):
            return r.json()["contact"]["id"]

    # Create
    parts = (name or "").split(None, 1)
    first_name = parts[0] if parts else ""
    last_name = parts[1] if len(parts) > 1 else ""
    r = requests.post(
        f"{GHL_BASE}/contacts/",
        headers=headers,
        json={
            "locationId": GHL_LOCATION_ID,
            "firstName": first_name,
            "lastName": last_name,
            "email": email,
            "phone": phone,
        },
    )
    if r.ok:
        return r.json().get("contact", {}).get("id")
    # GHL 400 sometimes returns existing contact ID
    if r.status_code == 400:
        meta = r.json().get("meta", {})
        if meta.get("contactId"):
            return meta["contactId"]
    return None


@ghl_safe
def tag_contact(contact_id, tags):
    """Add tags to a GHL contact."""
    requests.put(
        f"{GHL_BASE}/contacts/{contact_id}",
        headers=_headers(),
        json={"tags": tags},
    )


@ghl_safe
def add_note(contact_id, note_text):
    """Add a note to a GHL contact."""
    requests.post(
        f"{GHL_BASE}/contacts/{contact_id}/notes",
        headers=_headers(),
        json={"body": note_text},
    )


@ghl_safe
def on_session_created(session, ct):
    """Called when a new intake session is created — tag in GHL."""
    contact_id = find_or_create_contact(session.name, session.email, session.phone)
    if not contact_id:
        return

    from extensions import db
    session.ghl_contact_id = contact_id
    db.session.commit()

    prefix = ct.ghl_tag_prefix
    tag_contact(contact_id, [
        f"{prefix}_intake_started",
        f"{prefix}_pending",
    ])
    add_note(contact_id, f"Intake session started for {ct.display_name}")


@ghl_safe
def on_payment_complete(session, ct, agreement):
    """Called after successful payment — tag as hired."""
    contact_id = session.ghl_contact_id
    if not contact_id:
        contact_id = find_or_create_contact(session.name, session.email, session.phone)
    if not contact_id:
        return

    prefix = ct.ghl_tag_prefix
    tag_contact(contact_id, [
        f"{prefix}_hired",
        f"{prefix}_retainer_signed",
    ])
    amount_str = f"${agreement.amount / 100:,.2f}" if agreement.amount else "N/A"
    add_note(
        contact_id,
        f"Payment confirmed for {ct.display_name}: {amount_str}",
    )
