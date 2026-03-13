"""Dropbox upload for signed retainer PDFs → Clio-linked folders."""

import os
import logging

log = logging.getLogger("generic-intake.dropbox")

DROPBOX_APP_KEY = os.getenv("DROPBOX_APP_KEY", "")
DROPBOX_APP_SECRET = os.getenv("DROPBOX_APP_SECRET", "")
DROPBOX_REFRESH_TOKEN = os.getenv("DROPBOX_REFRESH_TOKEN", "")
DROPBOX_RETAINER_PATH = os.getenv("DROPBOX_RETAINER_PATH", "/Jared Jaskot/Clio/Jaskot Law")


def upload_retainer_to_dropbox(pdf_bytes, client_name, filename, matter_number=""):
    """Upload retainer PDF to Dropbox and return a shared download link.

    For Clio clients: saves to {DROPBOX_RETAINER_PATH}/{matter}-{name}/
    For new clients:  saves to {DROPBOX_RETAINER_PATH}/New Clients/{name}/

    Returns the shared link URL or None on failure.
    """
    if not DROPBOX_APP_KEY or not DROPBOX_APP_SECRET or not DROPBOX_REFRESH_TOKEN:
        log.warning("Dropbox credentials not configured, skipping upload")
        return None

    try:
        import dropbox

        dbx = dropbox.Dropbox(
            oauth2_refresh_token=DROPBOX_REFRESH_TOKEN,
            app_key=DROPBOX_APP_KEY,
            app_secret=DROPBOX_APP_SECRET,
        )

        safe_name = client_name.strip().replace("/", "-")
        if matter_number:
            folder = f"{DROPBOX_RETAINER_PATH}/{matter_number}-{safe_name}"
        else:
            folder = f"{DROPBOX_RETAINER_PATH}/New Clients/{safe_name}"
        full_path = f"{folder}/{filename}"

        dbx.files_upload(
            bytes(pdf_bytes) if isinstance(pdf_bytes, bytearray) else pdf_bytes,
            full_path,
            mode=dropbox.files.WriteMode.overwrite,
        )
        log.info("Retainer PDF uploaded to Dropbox: %s", full_path)

        # Create shared link
        try:
            link_meta = dbx.sharing_create_shared_link_with_settings(full_path)
            link_url = link_meta.url.replace("?dl=0", "?dl=1")
        except dropbox.exceptions.ApiError as e:
            if "shared_link_already_exists" in str(e):
                links = dbx.sharing_list_shared_links(path=full_path, direct_only=True)
                if links.links:
                    link_url = links.links[0].url.replace("?dl=0", "?dl=1")
                else:
                    link_url = None
            else:
                raise

        log.info("Dropbox shared link: %s", link_url)
        return link_url

    except Exception as e:
        log.error("Dropbox upload/link failed: %s", str(e))
        return None
