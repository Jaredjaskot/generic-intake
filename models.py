"""Database models for generic intake."""

from datetime import datetime, timezone

from extensions import db


class IntakeSession(db.Model):
    __tablename__ = "intake_session"

    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(64), unique=True, nullable=False, index=True)
    case_type = db.Column(db.String(50), nullable=False)

    # Client info
    name = db.Column(db.String(200))
    email = db.Column(db.String(200))
    phone = db.Column(db.String(30))
    lang = db.Column(db.String(5), default="en")

    # Booking
    booking_uid = db.Column(db.String(200))
    selected_slot = db.Column(db.String(100))
    appointment_type = db.Column(db.String(30))

    # GHL
    ghl_contact_id = db.Column(db.String(100))

    # Funnel tracking
    funnel_step = db.Column(db.String(30), default="started")
    source = db.Column(db.String(30), default="funnel")
    created_by = db.Column(db.String(100), default="")

    # Staff pricing overrides
    difficulty_surcharge = db.Column(db.Integer)  # cents
    discount_amount = db.Column(db.Integer)  # cents
    amount_paid_office = db.Column(db.Integer)  # cents
    payment_method_office = db.Column(db.String(50), default="")
    payment_note = db.Column(db.Text, default="")
    addon_amount = db.Column(db.Integer)  # cents
    attorney_note = db.Column(db.Text, default="")
    clio_matter_number = db.Column(db.String(50), default="")
    ip_hash = db.Column(db.String(64), default="")

    # Retainer content (per-session override — JSON blob, same shape as retainer_content.py dicts)
    retainer_content_json = db.Column(db.Text, nullable=True)

    # Custom case type
    custom_case_type_name = db.Column(db.String(200), default="")

    # Fee structure
    fee_type = db.Column(db.String(20), default="hourly")  # hourly, flat, hybrid, contingency
    initial_retainer_cents = db.Column(db.Integer, nullable=True)
    monthly_payment_cents = db.Column(db.Integer, nullable=True)
    monthly_start_date = db.Column(db.String(100), default="")
    trust_minimum_cents = db.Column(db.Integer, nullable=True)
    scope_text = db.Column(db.Text, default="")

    # Signing
    signing_attorney = db.Column(db.String(200), default="")
    client_signatory = db.Column(db.String(200), default="")

    # UTM
    utm_source = db.Column(db.String(200))
    utm_medium = db.Column(db.String(200))
    utm_campaign = db.Column(db.String(200))

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    agreement = db.relationship("Agreement", backref="intake_session", uselist=False)

    def to_dict(self):
        """Serialize all columns to a JSON-safe dict."""
        return {
            "id": self.id,
            "token": self.token,
            "case_type": self.case_type,
            "name": self.name,
            "email": self.email,
            "phone": self.phone,
            "lang": self.lang,
            "booking_uid": self.booking_uid,
            "selected_slot": self.selected_slot,
            "appointment_type": self.appointment_type,
            "ghl_contact_id": self.ghl_contact_id,
            "funnel_step": self.funnel_step,
            "source": self.source,
            "created_by": self.created_by,
            "difficulty_surcharge": self.difficulty_surcharge,
            "discount_amount": self.discount_amount,
            "amount_paid_office": self.amount_paid_office,
            "payment_method_office": self.payment_method_office,
            "payment_note": self.payment_note,
            "addon_amount": self.addon_amount,
            "attorney_note": self.attorney_note,
            "clio_matter_number": self.clio_matter_number,
            "ip_hash": self.ip_hash,
            "retainer_content_json": self.retainer_content_json,
            "custom_case_type_name": self.custom_case_type_name,
            "fee_type": self.fee_type,
            "initial_retainer_cents": self.initial_retainer_cents,
            "monthly_payment_cents": self.monthly_payment_cents,
            "monthly_start_date": self.monthly_start_date,
            "trust_minimum_cents": self.trust_minimum_cents,
            "scope_text": self.scope_text,
            "signing_attorney": self.signing_attorney,
            "client_signatory": self.client_signatory,
            "utm_source": self.utm_source,
            "utm_medium": self.utm_medium,
            "utm_campaign": self.utm_campaign,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Agreement(db.Model):
    __tablename__ = "agreement"

    id = db.Column(db.Integer, primary_key=True)
    intake_session_id = db.Column(
        db.Integer, db.ForeignKey("intake_session.id"), nullable=False
    )
    payment_intent_id = db.Column(db.String(200), unique=True, index=True)
    signature_data = db.Column(db.Text)
    signed_at = db.Column(db.DateTime)
    ip_address = db.Column(db.String(50))
    user_agent = db.Column(db.String(500))
    amount = db.Column(db.Integer)  # cents
    paid = db.Column(db.Boolean, default=False)
    paid_at = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
