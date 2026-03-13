"""API routes for intake sessions, payments, and Cal.com slots."""

import os
import logging

import stripe
from flask import Blueprint, request, jsonify

from jaskot_config import get as get_case_type
from models import IntakeSession, Agreement
from tokens import generate_token
from extensions import db

api_bp = Blueprint("api", __name__)
log = logging.getLogger("generic-intake.api")

stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")


@api_bp.route("/intake/api/create-session", methods=["POST"])
def create_session():
    """Create an IntakeSession with case_type, return token."""
    data = request.get_json(force=True)
    case_type_key = data.get("case_type", "")

    try:
        ct = get_case_type(case_type_key)
    except ValueError:
        return jsonify({"error": f"Unknown case type: {case_type_key}"}), 400

    token = generate_token()
    session = IntakeSession(
        token=token,
        case_type=case_type_key,
        name=data.get("name", ""),
        email=data.get("email", ""),
        phone=data.get("phone", ""),
        lang=data.get("lang", "en"),
        booking_uid=data.get("booking_uid", ""),
        selected_slot=data.get("selected_slot", ""),
        appointment_type=data.get("appointment_type", ""),
        utm_source=data.get("utm_source", ""),
        utm_medium=data.get("utm_medium", ""),
        utm_campaign=data.get("utm_campaign", ""),
    )
    db.session.add(session)
    db.session.commit()

    log.info("Created session %s for case_type=%s", token[:8], case_type_key)

    # Fire GHL tagging in background
    try:
        from integrations.ghl import on_session_created
        on_session_created(session, ct)
    except Exception:
        log.exception("GHL on_session_created failed (non-fatal)")

    return jsonify({"token": token, "session_id": session.id})


@api_bp.route("/intake/api/create-payment-intent", methods=["POST"])
def create_payment_intent():
    """Create a Stripe PaymentIntent for the retainer fee."""
    data = request.get_json(force=True)
    token = data.get("token", "")
    signature_data = data.get("signature", "")

    session = IntakeSession.query.filter_by(token=token).first()
    if not session:
        return jsonify({"error": "Invalid session"}), 400

    # Resolve base fee — per-session override or case type default
    is_custom = session.case_type == "custom"
    ct = None
    if not is_custom:
        try:
            ct = get_case_type(session.case_type)
        except ValueError:
            return jsonify({"error": "Unknown case type"}), 400

    # Calculate amount: base + surcharge - discount - office payment
    if session.initial_retainer_cents is not None:
        base = session.initial_retainer_cents
    elif ct is not None:
        base = ct.base_fee_cents
    else:
        base = 0
    surcharge = session.difficulty_surcharge or 0
    discount = session.discount_amount or 0
    office_paid = session.amount_paid_office or 0
    amount_cents = max(base + surcharge - discount - office_paid, 0)

    # Create or update Agreement
    agreement = Agreement.query.filter_by(intake_session_id=session.id).first()
    if not agreement:
        agreement = Agreement(intake_session_id=session.id)
        db.session.add(agreement)

    from datetime import datetime, timezone
    agreement.signature_data = signature_data
    agreement.signed_at = datetime.now(timezone.utc)
    agreement.ip_address = request.remote_addr
    agreement.user_agent = request.headers.get("User-Agent", "")[:500]
    agreement.amount = amount_cents
    db.session.commit()

    try:
        pi = stripe.PaymentIntent.create(
            amount=amount_cents,
            currency="usd",
            metadata={
                "case_type": session.case_type,
                "session_token": token,
                "client_name": session.name,
                "client_email": session.email,
                "client_phone": session.phone,
            },
        )
        agreement.payment_intent_id = pi.id
        session.funnel_step = "retainer_signed"
        db.session.commit()

        return jsonify({
            "clientSecret": pi.client_secret,
            "amount": amount_cents,
        })
    except stripe.StripeError as e:
        log.error("Stripe error: %s", e)
        return jsonify({"error": str(e)}), 500


@api_bp.route("/intake/api/slots/<case_type>")
def calcom_slots(case_type):
    """Proxy Cal.com tRPC slot availability."""
    try:
        ct = get_case_type(case_type)
    except ValueError:
        return jsonify({"error": "Unknown case type"}), 404

    from integrations.calcom import get_slots
    start = request.args.get("start", "")
    end = request.args.get("end", "")
    tz = request.args.get("timeZone", "America/New_York")

    slots = get_slots(ct, start, end, tz)
    return jsonify(slots)
