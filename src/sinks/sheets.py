from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone

import gspread
from google.oauth2.service_account import Credentials
from pydantic import BaseModel, ConfigDict, Field

from src.config import (
    ASSETS_SHEET_ID,
    ASSETS_WORKSHEET,
    FIXTURE_DIR,
    GOOGLE_SHEET_ID,
    SCOPES,
    USE_FIXTURE_DATA,
    get_service_account_path,
)
from src.models import SheetRow
from src.utils.logging import log


class AssetRecord(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str = Field("", alias="資產名稱")
    category: str = Field("", alias="資產類別")
    confidentiality: str = Field("", alias="機密等級")
    description: str = Field("", alias="資產描述")
    process: str = Field("", alias="業務流程/營運系統")
    department: str = Field("", alias="部門")
    user: str = Field("", alias="使用者(User)")
    owner: str = Field("", alias="擁有人(Owner)")


_TW = timezone(timedelta(hours=8))

INTEL_HEADERS = [
    "紀錄日期",
    "情資ID",
    "來源",
    "發布日期",
    "標題",
    "情資類型",
    "CVE ID",
    "建議措施",
    "風險等級",
    "摘要",
    "公司相關性",
    "受影響資產",
    "負責單位",
    "狀態",
    "追蹤連結",
    "備注",
    "完成日期",
    "處理人員",
    "通知時間",
    "TWCERT 影響等級",
    "參考網址",
]

_gc: gspread.Client | None = None
_spreadsheet: gspread.Spreadsheet | None = None
_assets_spreadsheet: gspread.Spreadsheet | None = None
_ws_cache: dict[str, gspread.Worksheet] = {}


def _ensure_client() -> gspread.Client:
    global _gc
    if _gc is None:
        creds = Credentials.from_service_account_file(get_service_account_path(), scopes=SCOPES)
        _gc = gspread.authorize(creds)
    return _gc


def _get_spreadsheet() -> gspread.Spreadsheet:
    global _spreadsheet
    if _spreadsheet is None:
        _spreadsheet = _ensure_client().open_by_key(GOOGLE_SHEET_ID)
    return _spreadsheet


def _get_assets_spreadsheet() -> gspread.Spreadsheet:
    global _assets_spreadsheet
    if _assets_spreadsheet is None:
        _assets_spreadsheet = _ensure_client().open_by_key(ASSETS_SHEET_ID)
    return _assets_spreadsheet


def _resolve_date_tab(publish_date: str) -> str:
    date_part = (publish_date or "")[:10].strip()
    if len(date_part) >= 7 and date_part[4] == "-":
        return date_part[:7]  # YYYY-MM
    return datetime.now(_TW).strftime("%Y-%m")


_COL_WIDTHS = [
    100,  # A 紀錄日期
    160,  # B 情資ID
    80,  # C 來源
    100,  # D 發布日期
    280,  # E 標題
    100,  # F 情資類型
    130,  # G CVE ID
    280,  # H 建議措施
    80,  # I 風險等級
    280,  # J 摘要
    100,  # K 公司相關性
    180,  # L 受影響資產
    80,  # M 負責單位
    80,  # N 狀態
    140,  # O 追蹤連結
    180,  # P 備注
    100,  # Q 完成日期
    80,  # R 處理人員
    120,  # S 通知時間
    100,  # T TWCERT 影響等級
    180,  # U 參考網址
]


# (col_index 0-based, values) for dropdown validation on data rows (startRowIndex=1)
_DROPDOWN_COLS: list[tuple[int, list[str]]] = [
    (8, ["Critical", "High", "Medium", "Low", "無"]),  # I 風險等級
    (10, ["H", "M", "L", "無"]),  # K 公司相關性
    (13, ["待處理", "處理中", "核可發佈", "已完成", "不適用"]),  # N 狀態
    (17, ["無"]),  # R 處理人員
]


def _dropdown_request(sid: int, col: int, values: list[str]) -> dict:
    return {
        "setDataValidation": {
            "range": {
                "sheetId": sid,
                "startRowIndex": 1,
                "startColumnIndex": col,
                "endColumnIndex": col + 1,
            },
            "rule": {
                "condition": {
                    "type": "ONE_OF_LIST",
                    "values": [{"userEnteredValue": v} for v in values],
                },
                "strict": False,
                "showCustomUi": True,
            },
        }
    }


def _format_worksheet(ws: gspread.Worksheet) -> None:
    sid = ws._properties["sheetId"]
    requests = (
        [
            {
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": sid,
                        "gridProperties": {"frozenRowCount": 1, "frozenColumnCount": 4},
                    },
                    "fields": "gridProperties(frozenRowCount,frozenColumnCount)",
                }
            },
            {
                "setBasicFilter": {
                    "filter": {"range": {"sheetId": sid, "startRowIndex": 0, "endColumnIndex": 21}}
                }
            },
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sid,
                        "startRowIndex": 0,
                        "endRowIndex": 1,
                        "endColumnIndex": 21,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "textFormat": {"bold": True},
                            "backgroundColor": {"red": 0.82, "green": 0.88, "blue": 0.95},
                        }
                    },
                    "fields": "userEnteredFormat(textFormat,backgroundColor)",
                }
            },
            {
                "repeatCell": {
                    "range": {"sheetId": sid, "endColumnIndex": 21},
                    "cell": {
                        "userEnteredFormat": {"wrapStrategy": "WRAP", "verticalAlignment": "TOP"}
                    },
                    "fields": "userEnteredFormat(wrapStrategy,verticalAlignment)",
                }
            },
            {
                "repeatCell": {
                    "range": {"sheetId": sid, "startColumnIndex": 20, "endColumnIndex": 21},
                    "cell": {"userEnteredFormat": {"wrapStrategy": "CLIP"}},
                    "fields": "userEnteredFormat.wrapStrategy",
                }
            },
        ]
        + [
            {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": sid,
                        "dimension": "COLUMNS",
                        "startIndex": i,
                        "endIndex": i + 1,
                    },
                    "properties": {"pixelSize": w},
                    "fields": "pixelSize",
                }
            }
            for i, w in enumerate(_COL_WIDTHS)
        ]
        + [_dropdown_request(sid, col, values) for col, values in _DROPDOWN_COLS]
    )
    ws.spreadsheet.batch_update({"requests": requests})


def _sort_worksheets_newest_first(ss: gspread.Spreadsheet) -> None:
    """Reorder YYYY-MM tabs descending; non-date tabs stay at the end."""
    sheets = ss.worksheets()
    date_tabs = sorted(
        [s for s in sheets if len(s.title) == 7 and s.title[4] == "-"],
        key=lambda s: s.title,
        reverse=True,
    )
    other_tabs = [s for s in sheets if s not in date_tabs]
    ordered = date_tabs + other_tabs
    requests = [
        {
            "updateSheetProperties": {
                "properties": {"sheetId": s.id, "index": i},
                "fields": "index",
            }
        }
        for i, s in enumerate(ordered)
    ]
    ss.batch_update({"requests": requests})


def _get_or_create_date_worksheet(date_str: str) -> gspread.Worksheet:
    if date_str in _ws_cache:
        return _ws_cache[date_str]
    ss = _get_spreadsheet()
    try:
        ws = ss.worksheet(date_str)
    except gspread.exceptions.WorksheetNotFound:
        ws = ss.add_worksheet(title=date_str, rows=1000, cols=21)
        ws.append_row(INTEL_HEADERS, value_input_option="USER_ENTERED")
        _format_worksheet(ws)
        _sort_worksheets_newest_first(ss)
        log.info("Created new worksheet: %s", date_str)
    _ws_cache[date_str] = ws
    return ws


def get_existing_intel_ids(dates: Iterable[str]) -> set[str]:
    ss = _get_spreadsheet()
    all_ids: set[str] = set()
    for date_str in dates:
        try:
            ws = ss.worksheet(date_str)
        except gspread.exceptions.WorksheetNotFound:
            continue
        col_b = ws.col_values(2)
        all_ids.update(col_b[1:])  # skip header
    return all_ids


def append_rows(rows: list[SheetRow]) -> int:
    if not rows:
        return 0

    by_date: dict[str, list[SheetRow]] = defaultdict(list)
    for row in rows:
        by_date[_resolve_date_tab(row.publish_date)].append(row)

    total = 0
    for date_str, date_rows in sorted(by_date.items()):
        ws = _get_or_create_date_worksheet(date_str)
        values = [r.to_row_list() for r in date_rows]
        ws.append_rows(values, value_input_option="USER_ENTERED")
        log.info("Appended %d rows to worksheet %s", len(values), date_str)
        total += len(values)

    return total


def load_assets_context() -> str:
    if USE_FIXTURE_DATA:
        path = FIXTURE_DIR / "sample_assets.json"
        with open(path, encoding="utf-8") as f:
            records = json.load(f)
    else:
        ws = _get_assets_spreadsheet().worksheet(ASSETS_WORKSHEET)
        records = ws.get_all_records()

    lines = []
    for r in records:
        asset = AssetRecord.model_validate(r)
        if not asset.name:
            continue
        lines.append(
            f"- {asset.name}（{asset.category}, {asset.confidentiality}）"
            f"— {asset.description}；"
            f"流程：{asset.process}；"
            f"部門：{asset.department}；"
            f"User：{asset.user}；"
            f"Owner：{asset.owner}"
        )
    return "\n".join(lines)


def select_relevant(records: list[dict]) -> list[dict]:
    return [r for r in records if str(r.get("公司相關性", "")).strip() not in ("", "無")]


def select_publishable(records: list[dict]) -> list[tuple[int, dict]]:
    picked: list[tuple[int, dict]] = []
    for i, r in enumerate(records):
        approved = str(r.get("狀態", "")).strip() == "核可發佈"
        unsent = not str(r.get("通知時間", "")).strip()
        if approved and unsent:
            picked.append((i, r))
    return picked
