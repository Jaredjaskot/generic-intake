"""Generate a signed retainer agreement PDF from content dict.

Uses fpdf2 (pure Python, no system deps). Returns PDF as bytes.
"""

import base64
import logging
import os
import tempfile
from datetime import datetime, timezone

from fpdf import FPDF

log = logging.getLogger("generic-intake.pdf")


class RetainerPDF(FPDF):
    """Custom PDF with header/footer for Jaskot Law retainer agreements."""

    def __init__(self, content, **kwargs):
        super().__init__(**kwargs)
        self.content = content

    def header(self):
        self.set_font("Helvetica", "B", 16)
        self.cell(0, 8, self.content["firm"]["name"], align="C", new_x="LMARGIN", new_y="NEXT")
        self.set_font("Helvetica", "", 9)
        self.cell(0, 5, self.content["firm"]["address"], align="C", new_x="LMARGIN", new_y="NEXT")
        self.cell(
            0, 5,
            f'{self.content["firm"]["phone"]}  |  {self.content["firm"]["email"]}',
            align="C", new_x="LMARGIN", new_y="NEXT",
        )
        self.ln(3)
        self.set_draw_color(139, 26, 26)
        self.set_line_width(0.5)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")
        self.set_text_color(0, 0, 0)


def _add_section_heading(pdf, text):
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, text, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)


def _add_body_text(pdf, text):
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 5, text)
    pdf.ln(3)


def _add_list_item(pdf, text, bullet="*"):
    pdf.set_font("Helvetica", "", 10)
    indent = 15
    pdf.set_x(pdf.l_margin + indent)
    width = pdf.w - pdf.l_margin - pdf.r_margin - indent
    pdf.multi_cell(width, 5, f"{bullet}  {text}")
    pdf.ln(1)


def generate_retainer_pdf(
    content,
    client_name,
    client_email,
    client_phone,
    lang,
    signature_base64,
    amount_cents,
    signed_at,
):
    """Generate a signed retainer agreement PDF.

    Args:
        content: Retainer content dict (from jaskot_config.get_retainer_content)
        client_name, client_email, client_phone: Client contact info
        lang: "en" or "es"
        signature_base64: Base64-encoded PNG signature image
        amount_cents: Payment amount in cents
        signed_at: datetime of signing

    Returns:
        PDF as bytes.
    """
    pdf = RetainerPDF(content, orientation="P", unit="mm", format="Letter")
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    # Title
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 8, content["title"], align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, content["subtitle"], align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)

    # Client Information
    _add_section_heading(pdf, "Client Information" if lang == "en" else "Información del Cliente")
    pdf.set_font("Helvetica", "", 10)
    name_label = "Name" if lang == "en" else "Nombre"
    email_label = "Email" if lang == "en" else "Correo"
    phone_label = "Phone" if lang == "en" else "Teléfono"
    pdf.cell(0, 5, f"{name_label}: {client_name}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 5, f"{email_label}: {client_email}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 5, f"{phone_label}: {client_phone}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    # Scope
    _add_section_heading(pdf, content["scope"]["heading"])
    _add_body_text(pdf, content["scope"]["text"])

    # Fees
    fees = content["fees"]
    _add_section_heading(pdf, fees["heading"])

    # Initial fee
    initial = fees["initial"]
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 7, f"{initial['label']}: ${initial['amount']:,}", new_x="LMARGIN", new_y="NEXT")

    # Monthly + min trust if present
    if "monthly" in fees:
        monthly = fees["monthly"]
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 6, f"{monthly['label']}: ${monthly['amount']:,}", new_x="LMARGIN", new_y="NEXT")
    if "min_trust" in fees:
        min_trust = fees["min_trust"]
        pdf.cell(0, 6, f"{min_trust['label']}: ${min_trust['amount']:,}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    # Includes
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 6, "Included:" if lang == "en" else "Incluido:", new_x="LMARGIN", new_y="NEXT")
    for item in fees["includes"]:
        _add_list_item(pdf, item, bullet="+")

    # Excludes
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 6, "Not Included:" if lang == "en" else "No Incluido:", new_x="LMARGIN", new_y="NEXT")
    for item in fees["excludes"]:
        _add_list_item(pdf, item, bullet="-")

    # Fee note
    pdf.set_font("Helvetica", "I", 9)
    pdf.multi_cell(0, 5, fees["note"])
    pdf.ln(3)

    # Terms
    for term in content["terms"]:
        _add_section_heading(pdf, term["heading"])
        _add_body_text(pdf, term["text"])
        if "items" in term:
            for item in term["items"]:
                _add_list_item(pdf, item, bullet="-")
            pdf.ln(2)
        if "text_after" in term:
            _add_body_text(pdf, term["text_after"])

    # Addon
    addon = content.get("addon")
    if addon:
        _add_section_heading(pdf, addon["heading"])
        _add_body_text(pdf, addon["text"])
        for term in content.get("addon_terms", []):
            _add_section_heading(pdf, term["heading"])
            _add_body_text(pdf, term["text"])
            if "items" in term:
                for item in term["items"]:
                    _add_list_item(pdf, item, bullet="-")
                pdf.ln(2)

    # Signature
    pdf.ln(5)
    sig = content["signature"]
    _add_section_heading(pdf, sig["client_label"])
    _add_body_text(pdf, sig["agreement_text"])

    if signature_base64:
        try:
            sig_data = signature_base64
            if "," in sig_data:
                sig_data = sig_data.split(",", 1)[1]
            img_bytes = base64.b64decode(sig_data)
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp.write(img_bytes)
                tmp_path = tmp.name
            pdf.image(tmp_path, x=pdf.l_margin, w=60, h=20)
            pdf.ln(2)
            os.unlink(tmp_path)
        except Exception as e:
            log.warning("Could not embed signature image: %s", e)
            pdf.set_font("Helvetica", "I", 10)
            pdf.cell(0, 5, "[Signature on file]", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 5, client_name, new_x="LMARGIN", new_y="NEXT")

    if signed_at:
        sign_date = signed_at.strftime("%B %d, %Y") if isinstance(signed_at, datetime) else str(signed_at)
    else:
        sign_date = datetime.now(timezone.utc).strftime("%B %d, %Y")
    pdf.cell(0, 5, f"{sig['date_label']}: {sign_date}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    # Payment Confirmation
    pdf.set_draw_color(139, 26, 26)
    pdf.set_line_width(0.3)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 6, "Payment Confirmed" if lang == "en" else "Pago Confirmado", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 5, f"{'Amount' if lang == 'en' else 'Monto'}: ${amount_cents / 100:,.2f}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 5, f"{'Date' if lang == 'en' else 'Fecha'}: {datetime.now(timezone.utc).strftime('%B %d, %Y')}", new_x="LMARGIN", new_y="NEXT")

    return pdf.output()
