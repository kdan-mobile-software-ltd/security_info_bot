from __future__ import annotations

import json

import gspread
from google.oauth2.service_account import Credentials

from src.config import (
    FIXTURE_DIR,
    GOOGLE_SHEET_ID,
    SCOPES,
    SHEET_ASSETS_WORKSHEET,
    SHEET_INTEL_WORKSHEET,
    SHEET_RULES_WORKSHEET,
    SHEET_UNITS_WORKSHEET,
    USE_FIXTURE_DATA,
    get_service_account_path,
)
from src.models import SheetRow
from src.utils.logging import log

_gc: gspread.Client | None = None
_spreadsheet: gspread.Spreadsheet | None = None


def _get_spreadsheet() -> gspread.Spreadsheet:
    global _gc, _spreadsheet
    if _spreadsheet is None:
        creds = Credentials.from_service_account_file(
            get_service_account_path(), scopes=SCOPES
        )
        _gc = gspread.authorize(creds)
        _spreadsheet = _gc.open_by_key(GOOGLE_SHEET_ID)
    return _spreadsheet


def get_existing_intel_ids() -> set[str]:
    ss = _get_spreadsheet()
    ws = ss.worksheet(SHEET_INTEL_WORKSHEET)
    col_b = ws.col_values(2)  # B column = intel_id
    return set(col_b[1:])  # skip header


def append_rows(rows: list[SheetRow]) -> int:
    if not rows:
        return 0

    ss = _get_spreadsheet()
    ws = ss.worksheet(SHEET_INTEL_WORKSHEET)

    values = [row.to_row_list() for row in rows]
    ws.append_rows(values, value_input_option="USER_ENTERED")
    log.info("Appended %d rows to Sheet", len(values))
    return len(values)


def update_notification_time(intel_id: str, notification_time: str) -> None:
    ss = _get_spreadsheet()
    ws = ss.worksheet(SHEET_INTEL_WORKSHEET)

    col_b = ws.col_values(2)
    for i, val in enumerate(col_b):
        if val == intel_id:
            ws.update_cell(i + 1, 19, notification_time)  # S column = 19
            break


def load_assets_context() -> str:
    if USE_FIXTURE_DATA:
        path = FIXTURE_DIR / "sample_assets.json"
        with open(path, encoding="utf-8") as f:
            assets = json.load(f)
        lines = []
        for a in assets:
            lines.append(f"- {a['category']}：{', '.join(a['items'])}（負責：{a['owner']}）")
        return "\n".join(lines)

    ss = _get_spreadsheet()
    ws = ss.worksheet(SHEET_ASSETS_WORKSHEET)
    records = ws.get_all_records()
    lines = []
    for r in records:
        lines.append(f"- {r.get('category', '')}：{r.get('items', '')}（負責：{r.get('owner', '')}）")
    return "\n".join(lines)


def load_units_context() -> str:
    if USE_FIXTURE_DATA:
        path = FIXTURE_DIR / "sample_units.json"
        with open(path, encoding="utf-8") as f:
            units = json.load(f)
        lines = []
        for u in units:
            lines.append(f"- {u['unit']}：{u['responsibility']}")
        return "\n".join(lines)

    ss = _get_spreadsheet()
    ws = ss.worksheet(SHEET_UNITS_WORKSHEET)
    records = ws.get_all_records()
    lines = []
    for r in records:
        lines.append(f"- {r.get('unit', '')}：{r.get('responsibility', '')}")
    return "\n".join(lines)


def load_rules_context() -> str:
    if USE_FIXTURE_DATA:
        path = FIXTURE_DIR / "sample_rules.md"
        return path.read_text(encoding="utf-8")

    ss = _get_spreadsheet()
    ws = ss.worksheet(SHEET_RULES_WORKSHEET)
    records = ws.get_all_records()
    lines = []
    for r in records:
        lines.append(f"- {r.get('rule', '')}")
    return "\n".join(lines)
