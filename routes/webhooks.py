"""Webhook handlers for Stripe and Cal.com."""

import os
import logging
import threading

import stripe
from flask import Blueprint, request, jsonify

from models import Agreement, IntakeSession
from extensions import db

webhooks_bp = Blueprint("webhooks", __name__)
log = logging.getLogger("generic-intake.webhooks")

stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")


@webhooks_bp.route("/intake/webhooks/stripe", methods=["POST"])
def stripe_webhook():
    """Handle Stripe payment_intent.succeeded events."""
    payload = request.get_data()
    sig_header = request.headers.get("Stripe-Signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except (ValueError, stripe.SignatureVerificationError) as e:
        log.warning("Stripe webhook verification failed: %s", e)
        return jsonify({"error": "Invalid signature"}), 400

    if event["type"] == "payment_intent.succeeded":
        pi = event["data"]["object"]
        _handle_payment_succeeded(pi)

    return jsonify({"received": True})


def _handle_payment_succeeded(pi_data):
    """Process successful payment — GHL tags, Slack, PDF."""
    pi_id = pi_data["id"]
    agreement = Agreement.query.filter_by(payment_intent_id=pi_id).first()
    if not agreement:
        log.warning("No agreement found for PI %s", pi_id)
        return

    from datetime import datetime, timezone
    agreement.paid = True
    agreement.paid_at = datetime.now(timezone.utc)
    db.session.commit()

    session = agreement.intake_session
    session.funnel_step = "paid"
    db.session.commit()

    # Run post-payment integrations in background thread
    from flask import current_app
    app = current_app._get_current_object()
    thread = threading.Thread(
        target=_process_post_payment,
        args=(app, session.id, agreement.id, pi_data.get("metadata", {})),
    )
    thread.start()


def _process_post_payment(app, session_id, agreement_id, metadata):
    """Post-payment: GHL tagging, Slack notification, PDF generation + email."""
    with app.app_context():
        session = IntakeSession.query.get(session_id)
        agreement = Agreement.query.get(agreement_id)
        if not session or not agreement:
            return

        from jaskot_config import get as get_case_type
        try:
            ct = get_case_type(session.case_type)
        except ValueError:
            if session.case_type != "custom":
                log.error("Unknown case type %s in post-payment", session.case_type)
                return
            ct = None

        # GHL tagging
        try:
            from integrations.ghl import on_payment_complete
            on_payment_complete(session, ct, agreement)
        except Exception:
            log.exception("GHL post-payment failed (non-fatal)")

        # Slack notification
        try:
            from integrations.slack import notify_payment
            notify_payment(session, ct, agreement.amount)
        except Exception:
            log.exception("Slack notification failed (non-fatal)")

        # PDF generation + email
        try:
            import json as _json
            from jaskot_config import get_retainer_content
            from pdf_generator import generate_retainer_pdf

            # Use per-session retainer content if available
            if session.retainer_content_json:
                content = _json.loads(session.retainer_content_json)
            else:
                content = get_retainer_content(session.case_type, session.lang or "en")
            pdf_bytes = generate_retainer_pdf(
                content=content,
                client_name=session.name,
                client_email=session.email,
                client_phone=session.phone,
                lang=session.lang or "en",
                signature_base64=agreement.signature_data or "",
                amount_cents=agreement.amount,
                signed_at=agreement.signed_at,
            )
            _email_pdf(session, pdf_bytes, ct, content)

            # Upload to Dropbox (Clio-linked folder)
            try:
                from integrations.dropbox_upload import upload_retainer_to_dropbox
                safe_name = session.name.strip().replace(" ", "_").replace("/", "-")
                filename = f"Jaskot_Law_Retainer_{safe_name}.pdf"
                upload_retainer_to_dropbox(
                    pdf_bytes=pdf_bytes,
                    client_name=session.name,
                    filename=filename,
                    matter_number=session.clio_matter_number or "",
                )
            except Exception:
                log.exception("Dropbox upload failed (non-fatal)")
        except Exception:
            log.exception("PDF generation/email failed (non-fatal)")


def _email_pdf(session, pdf_bytes, ct, content=None):
    """Email signed retainer PDF to client via Gmail API (HTTPS)."""
    if not session.email:
        log.info("Skipping PDF email — no client email")
        return

    # Resolve display name: case type object, custom name, or content title
    if ct is not None:
        display_name = ct.display_name
    elif session.custom_case_type_name:
        display_name = session.custom_case_type_name
    elif content and content.get("subtitle"):
        display_name = content["subtitle"]
    else:
        display_name = "Legal Services"

    staff_email = os.getenv("STAFF_NOTIFY_EMAIL", "jared@jaskot.law")
    lang = session.lang or "en"

    if lang == "es":
        subject = f"Su Contrato de Servicios Firmado — {display_name}"
        first_name = session.name.split()[0] if session.name else ""
        body = (
            f"Estimado/a {first_name},\n\n"
            f"Adjunto encontrará su contrato de servicios legales firmado para {display_name} "
            f"con Jaskot Law.\n\n"
            f"Por favor guarde este documento para sus registros. Si tiene alguna pregunta, "
            f"no dude en comunicarse con nosotros al (240) 607-5244 o info@jaskot.law.\n\n"
            f"Atentamente,\nJaskot Law"
        )
    else:
        subject = f"Your Signed Retainer Agreement — {display_name}"
        body = (
            f"Dear {session.name},\n\n"
            f"Please find attached your signed retainer agreement for {display_name} "
            f"with Jaskot Law.\n\n"
            f"If you have any questions, please contact us at info@jaskot.law or (240) 607-5244.\n\n"
            f"Best regards,\nJaskot Law"
        )

    from integrations.gmail_sender import send_email
    send_email(
        to_email=session.email,
        subject=subject,
        body=body,
        attachments=[("Retainer_Agreement.pdf", pdf_bytes)],
        bcc=staff_email,
    )
