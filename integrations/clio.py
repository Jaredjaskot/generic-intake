"""Clio integration — delegates to shared jaskot-clio package."""
import os
from jaskot_clio import ClioClient

_client = None

def _get_client():
    global _client
    if _client is None:
        _client = ClioClient(
            client_id=os.getenv("CLIO_CLIENT_ID", ""),
            client_secret=os.getenv("CLIO_CLIENT_SECRET", ""),
            token_file=os.getenv("CLIO_TOKEN_FILE", "clio_tokens.json"),
        )
    return _client

def lookup_matter(matter_number):
    return _get_client().lookup_by_matter(matter_number)

def lookup_contact(email):
    return _get_client().lookup_contact_by_email(email)
