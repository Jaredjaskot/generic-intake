"""Stripe payment integration."""

import os
import stripe

stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")


def create_payment_intent(amount_cents, metadata=None):
    """Create a Stripe PaymentIntent."""
    return stripe.PaymentIntent.create(
        amount=amount_cents,
        currency="usd",
        metadata=metadata or {},
    )
