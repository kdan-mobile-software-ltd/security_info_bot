from __future__ import annotations

from pathlib import Path

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from src.config import GOOGLE_DRIVE_IOC_FOLDER_ID, SCOPES, get_service_account_path
from src.utils.logging import log

_service = None


def _get_drive_service():
    global _service
    if _service is None:
        creds = Credentials.from_service_account_file(
            get_service_account_path(), scopes=SCOPES
        )
        _service = build("drive", "v3", credentials=creds)
    return _service


def upload_ioc_file(local_path: Path, filename: str | None = None) -> str:
    service = _get_drive_service()

    if filename is None:
        filename = local_path.name

    file_metadata = {
        "name": filename,
        "parents": [GOOGLE_DRIVE_IOC_FOLDER_ID],
    }
    media = MediaFileUpload(str(local_path), mimetype="text/plain")

    file = service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id, webViewLink",
    ).execute()

    web_link = file.get("webViewLink", "")
    file_id = file.get("id", "")

    service.permissions().create(
        fileId=file_id,
        body={"type": "anyone", "role": "reader"},
    ).execute()

    log.info("Uploaded IoC file %s to Drive: %s", filename, web_link)
    return web_link
