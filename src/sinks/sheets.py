from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import google.auth
import gspread
from google.oauth2.service_account import Credentials
from pydantic import BaseModel, ConfigDict, Field

from src.config import (
    ASSETS_SHEET_ID,
    ASSETS_WORKSHEET,
    FIXTURE_DIR,
    GOOGLE_SHEET_ID,
    POOL_WORKSHEET,
    SCOPES,
    USE_FIXTURE_DATA,
    get_service_account_path,
)
from src.models import AnalysisResult, IntelItem
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

# ── Schema constants ──────────────────────────────────────────────────────────
# POOL tab (8 columns A–H). The pool is maintained by the user and must already
# exist; the bot never writes these headers. Kept here as position documentation.
POOL_HEADERS = [
    "記錄日期",  # A idx0 — record date (append)
    "情資編號",  # B idx1 — intel_id (dedup key, append)
    "情資發布日期",  # C idx2 — publish_date (append)
    "情資內容",  # D idx3 — title (append)
    "建議措施",  # E idx4 — recommendation (backfill)
    "公司風險相關性 (H/M/L)",  # F idx5 — relevance label (backfill)
    "內部受影響資產",  # G idx6 — affected assets (backfill)
    "處置措施負責單位",  # H idx7 — responsible unit (backfill)
]

# MONTHLY tab (10 columns A–J). Bot writes these single-line headers when it
# creates a new monthly tab. Reads are always position-based (see _MONTHLY_KEY_POS).
MONTHLY_HEADERS = [
    "情資編號",  # A idx0
    "情資發布日期",  # B idx1
    "情資內容",  # C idx2
    "建議措施",  # D idx3
    "風險相關性 (H/M/L)",  # E idx4
    "內部受影響資產",  # F idx5
    "處置措施負責單位",  # G idx6
    "追蹤表單連結",  # H idx7 (human-filled)
    "狀態",  # I idx8
    "通知時間",  # J idx9
]

# Fixed ASCII-safe dict keys exposed by position-based monthly reads → column idx.
# 追蹤表單連結 (idx7) is intentionally not exposed (human-filled tracking link).
_MONTHLY_KEY_POS: dict[str, int] = {
    "情資編號": 0,
    "情資發布日期": 1,
    "情資內容": 2,
    "建議措施": 3,
    "相關性": 4,
    "受影響資產": 5,
    "負責單位": 6,
    "狀態": 8,
    "通知時間": 9,
}

# Ordered list of the exposed monthly dict keys (source of truth for templates).
MONTHLY_KEYS = list(_MONTHLY_KEY_POS.keys())

# Chinese relevance labels written to POOL/MONTHLY (bot never writes absolute risk
# levels like Critical/High). "重大相關" is a manual risk-team escalation option.
_RELEVANCE_LABELS = {"H": "高相關", "M": "中相關", "L": "低相關", "無": "無"}

_STATUS_VALUES = ["待處理", "處理中", "核可發佈", "已完成", "不適用"]
_STATUS_COL = 8  # column I (idx8)

_gc: gspread.Client | None = None
_spreadsheet: gspread.Spreadsheet | None = None
_assets_spreadsheet: gspread.Spreadsheet | None = None
_ws_cache: dict[str, gspread.Worksheet] = {}


def _ensure_client() -> gspread.Client:
    global _gc
    if _gc is None:
        sa_path = get_service_account_path()
        if sa_path:
            creds = Credentials.from_service_account_file(sa_path, scopes=SCOPES)
        else:
            # No SA key configured → use Application Default Credentials
            # (the attached service account on Cloud Run).
            creds, _ = google.auth.default(scopes=SCOPES)
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


# ── Relevance label ───────────────────────────────────────────────────────────
def relevance_label(relevance: str) -> str:
    """Map Gemini's H/M/L/無 to the Chinese label used in the Sheet.

    Unmapped values pass through unchanged (e.g. a manual "重大相關").
    """
    return _RELEVANCE_LABELS.get(relevance, relevance)


# ── Value builders (pure, unit-tested) ────────────────────────────────────────
def build_pool_raw_row(item: IntelItem, record_date: str) -> list[str]:
    """POOL append row (A–H); analysis columns E–H left blank until backfill."""
    return [record_date, item.intel_id, item.publish_date, item.title, "", "", "", ""]


def build_pool_backfill(analysis: AnalysisResult) -> list[str]:
    """POOL backfill values for range E:H."""
    return [
        analysis.recommendation,
        relevance_label(analysis.company_relevance),
        ", ".join(analysis.affected_assets),
        analysis.responsible_unit,
    ]


def build_monthly_row(item: IntelItem, analysis: AnalysisResult) -> list[str]:
    """MONTHLY append row (A–J)."""
    return [
        item.intel_id,
        item.publish_date,
        item.title,
        analysis.recommendation,
        relevance_label(analysis.company_relevance),
        ", ".join(analysis.affected_assets),
        analysis.responsible_unit,
        "",  # 追蹤表單連結 (human-filled)
        "待處理",  # 狀態
        "",  # 通知時間
    ]


def filter_monthly_pairs(
    pairs: list[tuple[IntelItem, AnalysisResult]],
) -> list[tuple[IntelItem, AnalysisResult]]:
    """Only intel with company_relevance != '無' goes to a monthly tab."""
    return [(item, analysis) for item, analysis in pairs if analysis.company_relevance != "無"]


# ── Tab helpers ───────────────────────────────────────────────────────────────
def _resolve_month_tab(publish_date: str) -> str:
    """`YYYY/MM` (slash) tab name from publish_date; current TW+8 month if absent."""
    date_part = (publish_date or "")[:10].strip()
    if len(date_part) >= 7 and date_part[4] == "-":
        return f"{date_part[:4]}/{date_part[5:7]}"
    return datetime.now(_TW).strftime("%Y/%m")


def _is_month_tab(title: str) -> bool:
    return len(title) == 7 and title[4] == "/" and title[:4].isdigit() and title[5:].isdigit()


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


def _get_pool_ws() -> gspread.Worksheet:
    key = f"__pool__::{POOL_WORKSHEET}"
    if key in _ws_cache:
        return _ws_cache[key]
    ss = _get_spreadsheet()
    try:
        ws = ss.worksheet(POOL_WORKSHEET)
    except gspread.exceptions.WorksheetNotFound as e:
        raise RuntimeError(
            f"POOL worksheet '{POOL_WORKSHEET}' not found in spreadsheet "
            f"{GOOGLE_SHEET_ID}. It must already exist (maintained manually); "
            "the bot does not create or format it."
        ) from e
    _ws_cache[key] = ws
    return ws


def _get_or_create_month_ws(month: str) -> gspread.Worksheet:
    if month in _ws_cache:
        return _ws_cache[month]
    ss = _get_spreadsheet()
    try:
        ws = ss.worksheet(month)
    except gspread.exceptions.WorksheetNotFound:
        ws = ss.add_worksheet(title=month, rows=1000, cols=len(MONTHLY_HEADERS))
        ws.append_row(MONTHLY_HEADERS, value_input_option="USER_ENTERED")
        sid = ws._properties["sheetId"]
        ws.spreadsheet.batch_update(
            {"requests": [_dropdown_request(sid, _STATUS_COL, _STATUS_VALUES)]}
        )
        # Deliberately no worksheet reordering — respect the user's tab order.
        log.info("Created monthly worksheet: %s", month)
    _ws_cache[month] = ws
    return ws


def _month_rows_from_values(values: list[list[str]]) -> list[dict]:
    """Position-based dicts for every data row (index i → sheet row i+2).

    Blank rows are kept (as all-empty dicts) so the list index stays aligned with
    the physical sheet row number; callers filter by content.
    """
    rows: list[dict] = []
    for raw in values[1:]:  # skip header
        rows.append(
            {
                key: (raw[pos].strip() if pos < len(raw) else "")
                for key, pos in _MONTHLY_KEY_POS.items()
            }
        )
    return rows


# ── POOL writes ───────────────────────────────────────────────────────────────
def get_existing_intel_ids() -> set[str]:
    """情資編號 already present in the POOL tab (dedup key = column B)."""
    ws = _get_pool_ws()
    col_b = ws.col_values(2)
    return {v.strip() for v in col_b[1:] if v.strip()}


def append_pool_raw(items: list[IntelItem]) -> list[IntelItem]:
    """Append raw rows for items not already in the pool; return the appended items."""
    if not items:
        return []
    ws = _get_pool_ws()
    seen = get_existing_intel_ids()
    record_date = datetime.now(_TW).strftime("%Y-%m-%d")
    new_items: list[IntelItem] = []
    values: list[list[str]] = []
    for item in items:
        if item.intel_id in seen:
            continue
        seen.add(item.intel_id)
        new_items.append(item)
        values.append(build_pool_raw_row(item, record_date))
    if values:
        ws.append_rows(values, value_input_option="USER_ENTERED")
        log.info("Pool: appended %d raw rows", len(values))
    return new_items


def backfill_pool_analysis(pairs: list[tuple[IntelItem, AnalysisResult]]) -> int:
    """Fill pool columns E–H for each intel_id, located by reading pool column B."""
    if not pairs:
        return 0
    ws = _get_pool_ws()
    col_b = ws.col_values(2)
    row_by_id = {v.strip(): i + 1 for i, v in enumerate(col_b) if v.strip()}
    updates: list[dict] = []
    for item, analysis in pairs:
        row = row_by_id.get(item.intel_id)
        if row is None:
            log.warning("Pool backfill: %s not found in pool, skipping", item.intel_id)
            continue
        updates.append({"range": f"E{row}:H{row}", "values": [build_pool_backfill(analysis)]})
    if updates:
        ws.batch_update(updates, value_input_option="USER_ENTERED")
        log.info("Pool: backfilled %d rows", len(updates))
    return len(updates)


# ── MONTHLY writes ────────────────────────────────────────────────────────────
def append_monthly(pairs: list[tuple[IntelItem, AnalysisResult]]) -> int:
    """Append relevance≠無 intel to its `YYYY/MM` tab (creating it if missing)."""
    relevant = filter_monthly_pairs(pairs)
    if not relevant:
        return 0
    by_month: dict[str, list[tuple[IntelItem, AnalysisResult]]] = defaultdict(list)
    for item, analysis in relevant:
        by_month[_resolve_month_tab(item.publish_date)].append((item, analysis))

    total = 0
    for month, month_pairs in sorted(by_month.items()):
        ws = _get_or_create_month_ws(month)
        col_a = ws.col_values(1)
        existing = {v.strip() for v in col_a[1:] if v.strip()}
        values: list[list[str]] = []
        for item, analysis in month_pairs:
            if item.intel_id in existing:
                continue
            existing.add(item.intel_id)
            values.append(build_monthly_row(item, analysis))
        if values:
            ws.append_rows(values, value_input_option="USER_ENTERED")
            log.info("Monthly %s: appended %d rows", month, len(values))
            total += len(values)
    return total


# ── MONTHLY reads ─────────────────────────────────────────────────────────────
def get_month_rows(month: str) -> list[dict]:
    ss = _get_spreadsheet()
    try:
        ws = ss.worksheet(month)
    except gspread.exceptions.WorksheetNotFound:
        return []
    return _month_rows_from_values(ws.get_all_values())


def month_tab_url(month: str) -> str:
    base = f"https://docs.google.com/spreadsheets/d/{GOOGLE_SHEET_ID}/edit"
    ss = _get_spreadsheet()
    try:
        ws = ss.worksheet(month)
    except gspread.exceptions.WorksheetNotFound:
        return base
    return f"{base}#gid={ws.id}"


def get_rows_for_publishing() -> list[dict]:
    ss = _get_spreadsheet()
    targets: list[dict] = []
    for ws in ss.worksheets():
        if not _is_month_tab(ws.title):
            continue
        records = _month_rows_from_values(ws.get_all_values())
        for i, rec in select_publishable(records):
            targets.append({"tab": ws.title, "row_number": i + 2, "record": rec})
    return targets


def mark_published(targets: list[dict], ts: str) -> None:
    by_tab: dict[str, list[int]] = defaultdict(list)
    for t in targets:
        by_tab[t["tab"]].append(t["row_number"])
    ss = _get_spreadsheet()
    for tab, row_numbers in by_tab.items():
        ws = ss.worksheet(tab)
        # column J (idx9) = 通知時間
        ws.batch_update([{"range": f"J{rn}", "values": [[ts]]} for rn in row_numbers])
        log.info("Marked %d rows published in %s", len(row_numbers), tab)


# ── Selectors (operate on position-based dicts) ───────────────────────────────
def select_relevant(records: list[dict]) -> list[dict]:
    return [r for r in records if str(r.get("相關性", "")).strip() not in ("", "無")]


def select_publishable(records: list[dict]) -> list[tuple[int, dict]]:
    picked: list[tuple[int, dict]] = []
    for i, r in enumerate(records):
        approved = str(r.get("狀態", "")).strip() == "核可發佈"
        unsent = not str(r.get("通知時間", "")).strip()
        if approved and unsent:
            picked.append((i, r))
    return picked


# ── Assets context ────────────────────────────────────────────────────────────
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
