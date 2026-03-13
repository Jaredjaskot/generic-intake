"""Staff routes — magic link generator, session lookup, payment processing."""

import hashlib
import json
import os
import logging
import secrets

import stripe
from flask import Blueprint, render_template, request, jsonify, redirect, session, url_for
from functools import wraps

from jaskot_config import get as get_case_type, all_case_types, choices, get_retainer_content
from models import IntakeSession, Agreement
from tokens import generate_token
from extensions import db

staff_bp = Blueprint("staff", __name__)
log = logging.getLogger("generic-intake.staff")

stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")


# --- Auth decorator ---

def require_staff_session(f):
    """Require cookie-based staff auth. Redirects to login if not authenticated."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("staff_authenticated"):
            return redirect(url_for("staff.login", next=request.path))
        return f(*args, **kwargs)
    return decorated


# --- Auth routes ---

@staff_bp.route("/intake/staff/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        admin_token = os.environ.get("ADMIN_AUTH_TOKEN", "")
        submitted = request.form.get("token", "")
        if admin_token and secrets.compare_digest(submitted, admin_token):
            session["staff_authenticated"] = True
            next_url = request.form.get("next") or url_for("staff.magic_link")
            return redirect(next_url)
        error = "Invalid token"
    return render_template("staff_login.html", error=error)


@staff_bp.route("/intake/staff/logout")
def logout():
    session.pop("staff_authenticated", None)
    return redirect(url_for("staff.login"))


# --- Magic Link Generator page ---

@staff_bp.route("/intake/staff/")
@require_staff_session
def magic_link():
    case_type_choices = choices()
    # Build fee map: {key: base_fee_dollars} for JS
    fee_map = {ct.key: ct.base_fee_cents // 100 for ct in all_case_types()}
    return render_template("staff_link.html", case_type_choices=case_type_choices, fee_map=fee_map)


# --- Staff API endpoints ---

@staff_bp.route("/intake/staff/api/generate-link", methods=["POST"])
@require_staff_session
def generate_link():
    """Generate a magic link for a client. Creates IntakeSession with staff overrides."""
    data = request.get_json(force=True)

    case_type_key = data.get("case_type", "")
    is_custom = case_type_key == "custom"

    if not is_custom:
        try:
            ct = get_case_type(case_type_key)
        except ValueError:
            return jsonify({"error": f"Unknown case type: {case_type_key}"}), 400

    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "Name is required"}), 400

    # Validate retainer_content_json if provided
    retainer_content_raw = data.get("retainer_content_json", "")
    if retainer_content_raw:
        if isinstance(retainer_content_raw, dict):
            retainer_content_raw = json.dumps(retainer_content_raw)
        else:
            try:
                json.loads(retainer_content_raw)
            except (json.JSONDecodeError, TypeError):
                return jsonify({"error": "retainer_content_json is not valid JSON"}), 400

    # Custom case types MUST have retainer_content_json
    if is_custom and not retainer_content_raw:
        return jsonify({"error": "Custom case types require retainer_content_json"}), 400

    token = generate_token()

    # Convert dollar amounts to cents
    surcharge_dollars = float(data.get("difficulty_surcharge", 0) or 0)
    discount_dollars = float(data.get("discount_amount", 0) or 0)
    office_dollars = float(data.get("amount_paid_office", 0) or 0)
    addon_dollars = float(data.get("addon_amount", 0) or 0)

    # Fee structure — dollar inputs converted to cents
    initial_retainer_dollars = float(data.get("initial_retainer", 0) or data.get("initial_retainer_cents", 0) or 0)
    monthly_payment_dollars = float(data.get("monthly_payment", 0) or data.get("monthly_payment_cents", 0) or 0)
    trust_minimum_dollars = float(data.get("trust_minimum", 0) or data.get("trust_minimum_cents", 0) or 0)

    # Enforce minimum addon of $1,000 if set
    if addon_dollars > 0 and addon_dollars < 1000:
        addon_dollars = 1000

    ip = request.remote_addr or ""
    ip_hash = hashlib.sha256(ip.encode()).hexdigest()[:16] if ip else ""

    intake_session = IntakeSession(
        token=token,
        case_type=case_type_key,
        name=name,
        email=data.get("email", "").strip(),
        phone=data.get("phone", "").strip(),
        lang=data.get("lang", "en"),
        source="staff_link",
        created_by=ip or "staff",
        ip_hash=ip_hash,
        clio_matter_number=data.get("clio_matter_number", "").strip(),
        difficulty_surcharge=int(surcharge_dollars * 100) if surcharge_dollars else None,
        discount_amount=int(discount_dollars * 100) if discount_dollars else None,
        amount_paid_office=int(office_dollars * 100) if office_dollars else None,
        payment_method_office=data.get("payment_method_office", ""),
        payment_note=data.get("payment_note", "").strip(),
        addon_amount=int(addon_dollars * 100) if addon_dollars else None,
        attorney_note=data.get("attorney_note", "").strip(),
        # Retainer builder fields
        retainer_content_json=retainer_content_raw or None,
        custom_case_type_name=data.get("custom_case_type_name", "").strip(),
        fee_type=data.get("fee_type", "hourly"),
        initial_retainer_cents=int(initial_retainer_dollars * 100) if initial_retainer_dollars else None,
        monthly_payment_cents=int(monthly_payment_dollars * 100) if monthly_payment_dollars else None,
        monthly_start_date=data.get("monthly_start_date", "").strip(),
        trust_minimum_cents=int(trust_minimum_dollars * 100) if trust_minimum_dollars else None,
        scope_text=data.get("scope_text", "").strip(),
        signing_attorney=data.get("signing_attorney", "").strip(),
        client_signatory=data.get("client_signatory", "").strip(),
    )
    db.session.add(intake_session)
    db.session.commit()

    log.info("Staff generated link: token=%s case_type=%s name=%s", token[:8], case_type_key, name)

    base_url = os.getenv("BASE_URL", "http://127.0.0.1:5001")
    lang = data.get("lang", "en")
    link = f"{base_url}/intake/{case_type_key}/retainer?token={token}&lang={lang}"

    return jsonify({"link": link, "token": token})


@staff_bp.route("/intake/staff/api/lookup-contact", methods=["POST"])
@require_staff_session
def lookup_contact():
    """Look up a GHL contact by email or phone."""
    data = request.get_json(force=True)
    email = data.get("email", "").strip()
    phone = data.get("phone", "").strip()

    if not email and not phone:
        return jsonify({"found": False, "error": "Email or phone required"})

    try:
        from integrations.ghl import find_or_create_contact, GHL_API_KEY, GHL_LOCATION_ID, GHL_BASE
        import requests as req

        headers = {
            "Authorization": f"Bearer {GHL_API_KEY}",
            "Content-Type": "application/json",
            "Version": "2021-07-28",
        }

        search_value = email or phone
        search_field = "email" if email else "phone"

        r = req.post(
            f"{GHL_BASE}/contacts/search/duplicate",
            headers=headers,
            json={"locationId": GHL_LOCATION_ID, search_field: search_value},
        )

        if r.ok and r.json().get("contact"):
            c = r.json()["contact"]
            return jsonify({
                "found": True,
                "name": f"{c.get('firstName', '')} {c.get('lastName', '')}".strip(),
                "email": c.get("email", ""),
                "phone": c.get("phone", ""),
                "tags": c.get("tags", []),
            })

        return jsonify({"found": False})
    except Exception:
        log.exception("GHL lookup failed")
        return jsonify({"found": False, "error": "Lookup failed"})


@staff_bp.route("/intake/staff/api/lookup-session", methods=["POST"])
@require_staff_session
def lookup_session():
    """Search intake sessions by token, name, email, or phone."""
    data = request.get_json(force=True)
    query = data.get("query", "").strip()

    if not query:
        return jsonify({"sessions": []})

    # Try exact token match
    s = IntakeSession.query.filter_by(token=query).first()
    if s:
        return jsonify({"sessions": [_session_to_dict(s)]})

    # Try exact email
    results = IntakeSession.query.filter_by(email=query).order_by(IntakeSession.created_at.desc()).limit(20).all()
    if results:
        return jsonify({"sessions": [_session_to_dict(s) for s in results]})

    # Try exact phone
    results = IntakeSession.query.filter_by(phone=query).order_by(IntakeSession.created_at.desc()).limit(20).all()
    if results:
        return jsonify({"sessions": [_session_to_dict(s) for s in results]})

    # Try name LIKE
    results = IntakeSession.query.filter(
        IntakeSession.name.ilike(f"%{query}%")
    ).order_by(IntakeSession.created_at.desc()).limit(20).all()

    return jsonify({"sessions": [_session_to_dict(s) for s in results]})


def _session_to_dict(s):
    """Convert IntakeSession to JSON-safe dict with calculated fields."""
    try:
        ct = get_case_type(s.case_type)
        base_amount = ct.base_fee_cents
    except ValueError:
        base_amount = 0

    # Use per-session initial_retainer_cents if set (custom or override)
    if s.initial_retainer_cents is not None:
        base_amount = s.initial_retainer_cents

    surcharge = s.difficulty_surcharge or 0
    discount = s.discount_amount or 0
    office_paid = s.amount_paid_office or 0
    charge_amount = max(base_amount + surcharge - discount - office_paid, 0)

    agreement = s.agreement

    return {
        "id": s.id,
        "token": s.token,
        "case_type": s.case_type,
        "name": s.name,
        "email": s.email,
        "phone": s.phone,
        "lang": s.lang,
        "source": s.source,
        "funnel_step": s.funnel_step,
        "selected_slot": s.selected_slot,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "base_amount": base_amount,
        "surcharge": surcharge,
        "discount": discount,
        "office_paid": office_paid,
        "charge_amount": charge_amount,
        "payment_method_office": s.payment_method_office,
        "payment_note": s.payment_note,
        "clio_matter_number": s.clio_matter_number,
        "attorney_note": s.attorney_note,
        "fee_type": s.fee_type or "hourly",
        "custom_case_type_name": s.custom_case_type_name or "",
        "has_custom_retainer": bool(s.retainer_content_json),
        "signed": bool(agreement and agreement.signature_data),
        "paid": bool(agreement and agreement.paid),
        "paid_at": agreement.paid_at.isoformat() if agreement and agreement.paid_at else None,
        "amount_paid": agreement.amount if agreement else None,
    }


# --- Case defaults API ---

@staff_bp.route("/intake/staff/api/case-defaults/<case_type>")
@require_staff_session
def case_defaults(case_type):
    """Return default retainer content dict for a case type + fee type + language."""
    fee_type = request.args.get("fee_type", "hourly")
    lang = request.args.get("lang", "en")

    # Try the new build_retainer_content (another agent is building this)
    try:
        from jaskot_config.retainer_templates import build_retainer_content
        content = build_retainer_content(case_type, lang, fee_type)
        return jsonify(content)
    except (ImportError, AttributeError):
        pass

    # Fall back to existing get_retainer_content
    try:
        content = get_retainer_content(case_type, lang)
        return jsonify(content)
    except ValueError:
        return jsonify({"error": f"No retainer content for {case_type}/{lang}"}), 404


# --- Preview retainer ---

@staff_bp.route("/intake/staff/api/preview-retainer", methods=["POST"])
@require_staff_session
def preview_retainer():
    """Render a retainer HTML fragment from a content dict for live preview."""
    data = request.get_json(force=True)
    content = data.get("content")
    if not content or not isinstance(content, dict):
        return jsonify({"error": "content dict is required"}), 400

    try:
        html = render_template(
            "retainer.html",
            case_type=data.get("case_type", "custom"),
            ct=None,
            lang=data.get("lang", "en"),
            token="",
            session=None,
            content=content,
            charge_cents=data.get("charge_cents", 0),
            stripe_public_key="",
            preview_mode=True,
        )
        return html, 200, {"Content-Type": "text/html; charset=utf-8"}
    except Exception as e:
        log.exception("Preview render failed")
        return jsonify({"error": str(e)}), 500


# --- Clio lookup ---

@staff_bp.route("/intake/staff/api/lookup-clio", methods=["POST"])
@require_staff_session
def lookup_clio():
    """Look up a Clio matter by number and return contact/matter info."""
    data = request.get_json(force=True)
    query = data.get("query", "").strip()
    if not query:
        return jsonify({"found": False, "error": "Query is required"}), 400

    try:
        from integrations.clio import lookup_matter
        result = lookup_matter(query)
        if result is None:
            return jsonify({"found": False})
        return jsonify(result)
    except Exception:
        log.exception("Clio lookup failed")
        return jsonify({"found": False, "error": "Clio lookup failed"})
