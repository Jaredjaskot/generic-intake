"""Page routes for the intake funnel."""

from flask import Blueprint, render_template, request, abort, redirect, url_for

from jaskot_config import get as get_case_type, get_retainer_content, get_document_checklist
from models import IntakeSession
from extensions import db

intake_bp = Blueprint("intake", __name__)


def _resolve_case_type(case_type_key, allow_custom=False):
    """Validate case_type against registry, abort 404 if unknown.

    If allow_custom is True, returns None for 'custom' case types instead of aborting.
    """
    if allow_custom and case_type_key == "custom":
        return None
    try:
        return get_case_type(case_type_key)
    except ValueError:
        abort(404)


@intake_bp.route("/intake/<case_type>/")
def landing(case_type):
    ct = _resolve_case_type(case_type)
    lang = request.args.get("lang", "en")
    return render_template(
        "landing.html",
        case_type=case_type,
        ct=ct,
        lang=lang,
    )


@intake_bp.route("/intake/<case_type>/book")
def book(case_type):
    ct = _resolve_case_type(case_type)
    lang = request.args.get("lang", "en")
    token = request.args.get("token", "")
    session = None
    if token:
        session = IntakeSession.query.filter_by(token=token).first()
    return render_template(
        "book.html",
        case_type=case_type,
        ct=ct,
        lang=lang,
        token=token,
        session=session,
    )


@intake_bp.route("/intake/<case_type>/retainer")
def retainer(case_type):
    ct = _resolve_case_type(case_type, allow_custom=True)
    lang = request.args.get("lang", "en")
    token = request.args.get("token", "")
    session_data = None
    if token:
        session_data = IntakeSession.query.filter_by(token=token).first()
    if not session_data:
        if case_type == "custom":
            abort(404)
        return redirect(url_for("intake.landing", case_type=case_type, lang=lang))

    import os
    import json as _json

    # Check for per-session retainer content override
    if session_data.retainer_content_json:
        content = _json.loads(session_data.retainer_content_json)
    elif case_type == "custom":
        # Custom case types MUST have retainer_content_json
        return redirect(url_for("intake.landing", case_type="asylum", lang=lang))
    else:
        content = get_retainer_content(case_type, lang)

    # Calculate charge amount (accounting for staff overrides)
    if session_data.initial_retainer_cents is not None:
        base = session_data.initial_retainer_cents
    elif ct is not None:
        base = ct.base_fee_cents
    else:
        base = 0

    surcharge = session_data.difficulty_surcharge or 0
    discount = session_data.discount_amount or 0
    office_paid = session_data.amount_paid_office or 0
    charge_cents = max(base + surcharge - discount - office_paid, 0)

    return render_template(
        "retainer.html",
        case_type=case_type,
        ct=ct,
        lang=lang,
        token=token,
        session=session_data,
        content=content,
        charge_cents=charge_cents,
        stripe_public_key=os.getenv("STRIPE_PUBLIC_KEY", ""),
    )


@intake_bp.route("/intake/<case_type>/confirmed")
def confirmed(case_type):
    ct = _resolve_case_type(case_type)
    lang = request.args.get("lang", "en")
    token = request.args.get("token", "")
    session = None
    if token:
        session = IntakeSession.query.filter_by(token=token).first()
    checklist = get_document_checklist(case_type, lang)
    return render_template(
        "confirmed.html",
        case_type=case_type,
        ct=ct,
        lang=lang,
        token=token,
        session=session,
        checklist=checklist,
    )
