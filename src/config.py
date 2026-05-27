import base64
import json
import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


TWCERT_ACCOUNT = os.environ.get("TWCERT_ACCOUNT", "")
TWCERT_PASSWORD = os.environ.get("TWCERT_PASSWORD", "")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.1-pro-preview")

GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "")
ASSETS_SHEET_ID = os.environ.get("ASSETS_SHEET_ID", "")
ASSETS_WORKSHEET = os.environ.get("ASSETS_WORKSHEET", "工作表1")

GIT_ARCHIVE_BRANCH = os.environ.get("GIT_ARCHIVE_BRANCH", "")
GIT_ARCHIVE_AUTO_PUSH = os.environ.get("GIT_ARCHIVE_AUTO_PUSH", "false").lower() == "true"

USE_FIXTURE_DATA = os.environ.get("USE_FIXTURE_DATA", "true").lower() == "true"
FIXTURE_DIR = Path(__file__).parent.parent / "tests" / "fixtures"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def get_service_account_path() -> str:
    sa_b64 = os.environ.get("GOOGLE_SA_JSON_B64", "")
    sa_file = os.environ.get("GOOGLE_SA_JSON_FILE", "")

    if sa_file and Path(sa_file).exists():
        return sa_file

    if sa_b64:
        sa_data = base64.b64decode(sa_b64)
        tmp = tempfile.NamedTemporaryFile(
            mode="wb", suffix=".json", delete=False, prefix="sa_"
        )
        tmp.write(sa_data)
        tmp.close()
        return tmp.name

    raise RuntimeError(
        "No Google Service Account credentials found. "
        "Set GOOGLE_SA_JSON_B64 or GOOGLE_SA_JSON_FILE."
    )
