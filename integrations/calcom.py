"""Cal.com slot fetching and booking proxy."""

import os
import logging

import requests

log = logging.getLogger("generic-intake.calcom")

CALCOM_INTERNAL_URL = os.getenv("CALCOM_INTERNAL_URL", "http://calcom:3000")


def get_slots(ct, start, end, timezone="America/New_York"):
    """Fetch available Cal.com slots for a case type's event."""
    event_type_id = ct.calcom_event_type_id
    if not event_type_id:
        log.warning("No calcom_event_type_id for %s", ct.key)
        return {"slots": {}}

    url = (
        f"{CALCOM_INTERNAL_URL}/api/trpc/viewer.slots.getSchedule"
        f"?input=%7B%22json%22%3A%7B%22isTeamEvent%22%3Afalse"
        f"%2C%22usernameList%22%3A%5B%5D"
        f"%2C%22eventTypeSlug%22%3A%22%22"
        f"%2C%22eventTypeId%22%3A{event_type_id}"
        f"%2C%22startTime%22%3A%22{start}%22"
        f"%2C%22endTime%22%3A%22{end}%22"
        f"%2C%22timeZone%22%3A%22{timezone}%22%7D%7D"
    )

    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        return data.get("result", {}).get("data", {}).get("json", {}).get("slots", {})
    except Exception:
        log.exception("Cal.com slot fetch failed")
        return {"slots": {}}


def create_booking(ct, name, email, start_time, timezone="America/New_York", notes=""):
    """Create a Cal.com booking."""
    event_type_id = ct.calcom_event_type_id
    if not event_type_id:
        return None

    url = f"{CALCOM_INTERNAL_URL}/api/bookings"
    payload = {
        "eventTypeId": event_type_id,
        "start": start_time,
        "timeZone": timezone,
        "language": "en",
        "responses": {
            "name": name,
            "email": email,
            "notes": notes,
        },
        "metadata": {},
    }

    try:
        r = requests.post(url, json=payload, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception:
        log.exception("Cal.com booking failed")
        return None
