"""Secure token generation for intake sessions."""

import secrets


def generate_token(nbytes=32):
    """Generate a cryptographically secure URL-safe token (256 bits)."""
    return secrets.token_urlsafe(nbytes)
