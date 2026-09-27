"""Generate docs/security-policy.pdf for the demo repo (the document Bob reads with /decisions)."""
import sys
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

SECTIONS = [
    ("1. Scope", "This policy applies to every service in the Acme Accounts platform, including the login "
                 "service in this repository. It is maintained by the Platform Security team."),
    ("2. Authentication code", "Changes to app/auth.py require a review by the security team before they are "
                               "merged. Password comparison must remain constant-time."),
    ("3. Dependencies", "Services must use only the Python standard library. New third-party dependencies "
                        "require written approval from Platform Security."),
    ("4. Testing", "Every behavior change must ship with a test that fails without the change. Tests that "
                   "do not assert on the changed behavior do not count."),
    ("5. Incident history", "In 2025 a rate-limit bypass in a sister service went unnoticed for three weeks "
                            "because its tests only exercised the happy path."),
]


def build(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    story = [Paragraph("Acme Accounts - Engineering Security Policy v1.2", styles["Title"]), Spacer(1, 12)]
    for head, body in SECTIONS:
        story += [Paragraph(head, styles["Heading2"]), Paragraph(body, styles["BodyText"]), Spacer(1, 8)]
    # Bob's PDF reader rejected ReportLab's defaults (probe, Sept 27): the compressed page stream gave
    # "Command token too long", and the 4 binary marker bytes on line 2, decoded as UTF-8, grew to 12 and
    # shifted every offset after them ("bad XRef entry"). Uncompressed and ASCII-only reads fine; the
    # same-length ASCII marker keeps the offsets valid, and the marker is optional.
    SimpleDocTemplate(str(path), pagesize=A4, title="Engineering Security Policy", pageCompression=0).build(story)
    data = path.read_bytes().replace(b"%\x93\x8c\x8b\x9e", b"%    ", 1)
    assert data.isascii(), "Bob can't read a PDF with non-ASCII bytes"
    path.write_bytes(data)


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else "docs/security-policy.pdf")
