from __future__ import annotations

import html as html_lib
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid
from pathlib import Path

from src.config import (
    EMAIL_FROM,
    INTERNAL_ANNOUNCE_EMAILS,
    OPS_ALERT_EMAILS,
    RISK_TEAM_EMAILS,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USER,
    USE_FIXTURE_DATA,
)
from src.notifiers.templates import render_internal_cards, render_risk_digest
from src.utils.errors import send_ops_alert
from src.utils.logging import log

_TW = timezone(timedelta(hours=8))
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _preview(kind: str, html: str) -> Path:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(_TW).strftime("%Y%m%d_%H%M%S")
    path = _DATA_DIR / f"email_preview_{kind}_{ts}.html"
    path.write_text(html, encoding="utf-8")
    log.info("[EMAIL PREVIEW] wrote %s", path)
    return path


def _smtp_send(subject: str, html: str, recipients: list[str]) -> bool:
    if not recipients:
        log.warning("No recipients configured, skipping send: %s", subject)
        return False
    msg = MIMEText(html, "html", "utf-8")
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = ", ".join(recipients)
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(EMAIL_FROM, recipients, msg.as_string())
        log.info("Sent '%s' to %d recipients", subject, len(recipients))
        return True
    except Exception as e:
        log.error("SMTP send failed: %s", e)
        send_ops_alert("Email 寄送失敗", f"{subject}\n{e}")
        return False


def send_risk_digest(
    month: str, records: list[dict], sheet_url: str, dry_run: bool = False
) -> bool:
    subject = f"[資安情資] {month} 風險小組月會彙整（{len(records)} 筆）"
    html = render_risk_digest(month, records, sheet_url)
    if dry_run or USE_FIXTURE_DATA:
        _preview("risk", html)
        return True
    return _smtp_send(subject, html, RISK_TEAM_EMAILS)


def send_internal_announcement(records: list[dict], dry_run: bool = False) -> bool:
    subject = f"[資安情資公告] {len(records)} 筆已核可情資"
    html = render_internal_cards(records)
    if dry_run or USE_FIXTURE_DATA:
        _preview("internal", html)
        return True
    return _smtp_send(subject, html, INTERNAL_ANNOUNCE_EMAILS)


def send_ops_email(title: str, detail: str, dry_run: bool = False) -> bool:
    """Send an ops alert by email, and keep emitting the existing [OPS] log line."""
    send_ops_alert(title, detail)
    subject = f"[資安情資][OPS] {title}"
    body = html_lib.escape(detail).replace("\n", "<br>")
    html = (
        '<html><body style="font-family: sans-serif;">'
        f"<h3>{html_lib.escape(title)}</h3>"
        f"<p>{body}</p>"
        "</body></html>"
    )
    if dry_run or USE_FIXTURE_DATA:
        _preview("ops", html)
        return True
    return _smtp_send(subject, html, OPS_ALERT_EMAILS)
