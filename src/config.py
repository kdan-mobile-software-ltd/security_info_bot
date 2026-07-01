import base64
import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


TWCERT_ACCOUNT = os.environ.get("TWCERT_ACCOUNT", "")
TWCERT_PASSWORD = os.environ.get("TWCERT_PASSWORD", "")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")

GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "")
ASSETS_SHEET_ID = os.environ.get("ASSETS_SHEET_ID", "")
ASSETS_WORKSHEET = os.environ.get("ASSETS_WORKSHEET", "工作表1")

GIT_ARCHIVE_BRANCH = os.environ.get("GIT_ARCHIVE_BRANCH", "")
GIT_ARCHIVE_AUTO_PUSH = os.environ.get("GIT_ARCHIVE_AUTO_PUSH", "false").lower() == "true"

USE_FIXTURE_DATA = os.environ.get("USE_FIXTURE_DATA", "true").lower() == "true"
FIXTURE_DIR = Path(__file__).parent.parent / "tests" / "fixtures"

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT") or "587")
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
EMAIL_FROM = os.environ.get("EMAIL_FROM", "") or SMTP_USER


def parse_emails(raw: str | None) -> list[str]:
    return [e.strip() for e in (raw or "").split(",") if e.strip()]


RISK_TEAM_EMAILS = parse_emails(os.environ.get("RISK_TEAM_EMAILS", ""))
INTERNAL_ANNOUNCE_EMAILS = parse_emails(os.environ.get("INTERNAL_ANNOUNCE_EMAILS", ""))

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def get_service_account_path() -> str | None:
    """Return a path to the SA JSON if configured via env, else None.

    Returns None when neither GOOGLE_SA_JSON_FILE nor GOOGLE_SA_JSON_B64 is set,
    so callers can fall back to Application Default Credentials (e.g. the
    attached service account on Cloud Run).
    """
    sa_b64 = os.environ.get("GOOGLE_SA_JSON_B64", "")
    sa_file = os.environ.get("GOOGLE_SA_JSON_FILE", "")

    if sa_file and Path(sa_file).exists():
        return sa_file

    if sa_b64:
        sa_data = base64.b64decode(sa_b64)
        tmp = tempfile.NamedTemporaryFile(mode="wb", suffix=".json", delete=False, prefix="sa_")
        tmp.write(sa_data)
        tmp.close()
        return tmp.name

    return None
