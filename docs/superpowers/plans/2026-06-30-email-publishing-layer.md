# Email Publishing Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a two-stage, human-gated email layer on top of the existing pipeline — a monthly risk-team digest (Stage 4a) and a post-meeting internal publish to RD managers (Stage 4b).

**Architecture:** Two new independent CLI modes (`--notify-risk`, `--publish-internal`) decoupled from the daily fetch/analyze/write pipeline. Stage 4a reads the current month's Sheet tab, filters company-relevant rows, and emails a digest to the risk team. The risk team reviews/edits directly in the Sheet and sets N「狀態」=「核可發佈」. Stage 4b scans all month tabs for approved-and-not-yet-published rows, emails their current (meeting-revised) values to RD managers, and stamps S「通知時間」as the published flag. Email goes out via SMTP. Selection/render logic is split into pure, unit-testable functions; gspread I/O wrappers stay thin.

**Tech Stack:** Python 3.11+, stdlib `smtplib` + `email.mime.text` (no new dependencies), gspread, pydantic, pytest, ruff, uv, GitHub Actions.

## Global Constraints

- Python `>=3.11`; every new module starts with `from __future__ import annotations`.
- No new runtime dependencies — use stdlib `smtplib` / `email` only.
- ruff: `line-length = 100`, lint select `E, F, W, I, UP, B`; code must pass `uv run ruff check .` and `uv run ruff format --check .`.
- Use the existing structured logger: `from src.utils.logging import log`.
- Timezone constant for stamps/filenames: `_TW = timezone(timedelta(hours=8))`.
- Sheet column contract (1-based): N「狀態」= col 14, S「通知時間」= col 19. Record dicts from `ws.get_all_records()` are keyed by the Chinese headers in `INTEL_HEADERS`.
- Approval value is the literal string `核可發佈`; relevance "none" value is the literal `無`.
- Commit after every task. Run tests/lint before each commit.

---

### Task 1: Email config (env vars + recipient parsing)

**Files:**
- Modify: `src/config.py` (append after the `USE_FIXTURE_DATA` / `FIXTURE_DIR` block, before `SCOPES`)
- Test: `tests/test_config_emails.py`

**Interfaces:**
- Produces: `parse_emails(raw: str) -> list[str]`; module constants `SMTP_HOST: str`, `SMTP_PORT: int`, `SMTP_USER: str`, `SMTP_PASSWORD: str`, `EMAIL_FROM: str`, `RISK_TEAM_EMAILS: list[str]`, `INTERNAL_ANNOUNCE_EMAILS: list[str]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_config_emails.py`:

```python
from src.config import parse_emails


def test_parse_emails_splits_and_strips():
    assert parse_emails("a@co, b@co ,c@co") == ["a@co", "b@co", "c@co"]


def test_parse_emails_empty_returns_empty_list():
    assert parse_emails("") == []
    assert parse_emails(None) == []


def test_parse_emails_drops_blank_segments():
    assert parse_emails("a@co,,") == ["a@co"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config_emails.py -v`
Expected: FAIL with `ImportError: cannot import name 'parse_emails'`

- [ ] **Step 3: Implement the minimal code**

In `src/config.py`, add after the `FIXTURE_DIR = ...` line:

```python
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT") or "587")
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
EMAIL_FROM = os.environ.get("EMAIL_FROM", "") or SMTP_USER


def parse_emails(raw: str | None) -> list[str]:
    return [e.strip() for e in (raw or "").split(",") if e.strip()]


RISK_TEAM_EMAILS = parse_emails(os.environ.get("RISK_TEAM_EMAILS", ""))
INTERNAL_ANNOUNCE_EMAILS = parse_emails(os.environ.get("INTERNAL_ANNOUNCE_EMAILS", ""))
```

Note: `int(os.environ.get("SMTP_PORT") or "587")` tolerates an unset secret that arrives as an empty string in CI.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config_emails.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/config.py tests/test_config_emails.py
git commit -m "feat(config): SMTP/email env vars + parse_emails helper"
```

---

### Task 2: Pure selection helpers + status dropdown value (sheets.py)

**Files:**
- Modify: `src/sinks/sheets.py` (add two module-level functions near the bottom; edit `_DROPDOWN_COLS`)
- Test: `tests/test_publish_scan.py`

**Interfaces:**
- Produces: `select_relevant(records: list[dict]) -> list[dict]` (keeps rows whose `公司相關性` is not `""`/`無`); `select_publishable(records: list[dict]) -> list[tuple[int, dict]]` (returns `(index, record)` where `狀態 == "核可發佈"` and `通知時間` is blank). Index is 0-based into `records`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_publish_scan.py`:

```python
from src.sinks.sheets import select_publishable, select_relevant


def _rec(rid, relevance="H", status="待處理", notified=""):
    return {
        "情資ID": rid,
        "標題": f"title-{rid}",
        "公司相關性": relevance,
        "狀態": status,
        "通知時間": notified,
    }


def test_select_relevant_excludes_none_and_blank():
    records = [
        _rec("a", relevance="H"),
        _rec("b", relevance="無"),
        _rec("c", relevance=""),
        _rec("d", relevance="M"),
    ]
    kept = [r["情資ID"] for r in select_relevant(records)]
    assert kept == ["a", "d"]


def test_select_publishable_only_approved_and_unsent():
    records = [
        _rec("a", status="核可發佈", notified=""),        # selected
        _rec("b", status="核可發佈", notified="2026-06-30"),  # already sent
        _rec("c", status="待處理", notified=""),           # not approved
        _rec("d", status="核可發佈", notified=""),         # selected
    ]
    picked = select_publishable(records)
    assert [(i, r["情資ID"]) for i, r in picked] == [(0, "a"), (3, "d")]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_publish_scan.py -v`
Expected: FAIL with `ImportError: cannot import name 'select_publishable'`

- [ ] **Step 3: Implement the minimal code**

In `src/sinks/sheets.py`, change the N「狀態」row of `_DROPDOWN_COLS`:

```python
    (13, ["待處理", "處理中", "核可發佈", "已完成", "不適用"]),  # N 狀態
```

Then add at the end of the file:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_publish_scan.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/sinks/sheets.py tests/test_publish_scan.py
git commit -m "feat(sheets): select_relevant/select_publishable + 核可發佈 dropdown"
```

---

### Task 3: HTML templates (pure renderers)

**Files:**
- Create: `src/notifiers/__init__.py` (empty)
- Create: `src/notifiers/templates.py`
- Test: `tests/test_email_render.py`

**Interfaces:**
- Produces: `render_risk_digest(month: str, records: list[dict], sheet_url: str) -> str`; `render_internal_cards(records: list[dict]) -> str`. Both return full HTML documents; inputs are Sheet record dicts keyed by the Chinese headers.

- [ ] **Step 1: Write the failing test**

Create `tests/test_email_render.py`:

```python
from src.notifiers.templates import render_internal_cards, render_risk_digest


def _rec(rid="X1", title="Apache RCE", risk="Critical", relevance="H",
         cve="CVE-2024-1\nCVE-2024-2", summary="摘要內容", reco="升級版本",
         assets="對外 Web", source="TWCERT"):
    return {
        "情資ID": rid, "標題": title, "風險等級": risk, "公司相關性": relevance,
        "CVE ID": cve, "摘要": summary, "建議措施": reco,
        "受影響資產": assets, "來源": source,
    }


def test_risk_digest_contains_key_fields_and_link():
    html = render_risk_digest("2026-06", [_rec()], "https://sheet/url#gid=1")
    assert "2026-06" in html
    assert "Apache RCE" in html
    assert "Critical" in html
    assert "https://sheet/url#gid=1" in html
    assert "核可發佈" in html  # instructs the team how to approve


def test_internal_cards_contains_key_fields():
    html = render_internal_cards([_rec()])
    assert "Apache RCE" in html
    assert "Critical" in html
    assert "摘要內容" in html
    assert "升級版本" in html


def test_renderers_escape_html():
    html = render_internal_cards([_rec(title="<script>x</script>")])
    assert "<script>x</script>" not in html
    assert "&lt;script&gt;" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_email_render.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.notifiers'`

- [ ] **Step 3: Implement the minimal code**

Create `src/notifiers/__init__.py` (empty file).

Create `src/notifiers/templates.py`:

```python
from __future__ import annotations

from html import escape


def _cell(value: object) -> str:
    return escape(str(value if value is not None else ""))


def render_risk_digest(month: str, records: list[dict], sheet_url: str) -> str:
    rows = []
    for r in records:
        cve = _cell(r.get("CVE ID")).replace("\n", "<br>")
        rows.append(
            "<tr>"
            f"<td>{_cell(r.get('情資ID'))}</td>"
            f"<td>{_cell(r.get('標題'))}</td>"
            f"<td>{_cell(r.get('風險等級'))}</td>"
            f"<td>{_cell(r.get('公司相關性'))}</td>"
            f"<td>{cve}</td>"
            f"<td>{_cell(r.get('摘要'))}</td>"
            f"<td>{_cell(r.get('建議措施'))}</td>"
            f"<td>{_cell(r.get('受影響資產'))}</td>"
            "</tr>"
        )
    body = "".join(rows)
    return (
        "<html><body>"
        f"<h2>{_cell(month)} 資安情資月會彙整（{len(records)} 筆與公司相關）</h2>"
        f'<p>請於月會中至 <a href="{_cell(sheet_url)}">Google Sheet（{_cell(month)}）</a> '
        "檢視與修改，並將要對外公告者「狀態」設為「核可發佈」。</p>"
        '<table border="1" cellpadding="6" cellspacing="0">'
        "<tr><th>情資ID</th><th>標題</th><th>風險等級</th><th>相關性</th>"
        "<th>CVE</th><th>摘要</th><th>建議措施</th><th>受影響資產</th></tr>"
        f"{body}</table></body></html>"
    )


def render_internal_cards(records: list[dict]) -> str:
    cards = []
    for r in records:
        cve = _cell(r.get("CVE ID")).replace("\n", ", ")
        cards.append(
            '<div style="border:1px solid #ccc;border-radius:8px;padding:12px;margin:12px 0">'
            f"<h3>{_cell(r.get('標題'))}</h3>"
            f"<p><b>風險等級：</b>{_cell(r.get('風險等級'))}　"
            f"<b>來源：</b>{_cell(r.get('來源'))}　"
            f"<b>CVE：</b>{cve}</p>"
            f"<p><b>摘要：</b>{_cell(r.get('摘要'))}</p>"
            f"<p><b>建議措施：</b>{_cell(r.get('建議措施'))}</p>"
            f"<p><b>受影響資產：</b>{_cell(r.get('受影響資產'))}</p>"
            "</div>"
        )
    body = "".join(cards)
    return f"<html><body><h2>資安情資公告（{len(records)} 筆）</h2>{body}</body></html>"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_email_render.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/notifiers/__init__.py src/notifiers/templates.py tests/test_email_render.py
git commit -m "feat(notifiers): HTML templates for risk digest + internal cards"
```

---

### Task 4: SMTP email sender

**Files:**
- Create: `src/notifiers/email.py`
- Test: `tests/test_email_send.py`

**Interfaces:**
- Consumes: config constants from Task 1; `render_risk_digest` / `render_internal_cards` from Task 3.
- Produces: `send_risk_digest(month: str, records: list[dict], sheet_url: str, dry_run: bool = False) -> bool`; `send_internal_announcement(records: list[dict], dry_run: bool = False) -> bool`. In `dry_run` OR fixture mode (`USE_FIXTURE_DATA`), both write a preview HTML file to `src/data/email_preview_{kind}_{ts}.html` and return `True` without sending.

- [ ] **Step 1: Write the failing test**

Create `tests/test_email_send.py`:

```python
from src.notifiers import email as email_mod


def test_dry_run_writes_preview_and_returns_true(tmp_path, monkeypatch):
    monkeypatch.setattr(email_mod, "_DATA_DIR", tmp_path)
    ok = email_mod.send_internal_announcement([{"標題": "t", "風險等級": "High"}], dry_run=True)
    assert ok is True
    previews = list(tmp_path.glob("email_preview_internal_*.html"))
    assert len(previews) == 1
    assert "風險等級" in previews[0].read_text(encoding="utf-8")


def test_risk_digest_dry_run_writes_preview(tmp_path, monkeypatch):
    monkeypatch.setattr(email_mod, "_DATA_DIR", tmp_path)
    ok = email_mod.send_risk_digest("2026-06", [{"標題": "t"}], "https://u", dry_run=True)
    assert ok is True
    assert list(tmp_path.glob("email_preview_risk_*.html"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_email_send.py -v`
Expected: FAIL with `ModuleNotFoundError` / `AttributeError: module ... has no attribute '_DATA_DIR'`

- [ ] **Step 3: Implement the minimal code**

Create `src/notifiers/email.py`:

```python
from __future__ import annotations

import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from pathlib import Path

from src.config import (
    EMAIL_FROM,
    INTERNAL_ANNOUNCE_EMAILS,
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_email_send.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/notifiers/email.py tests/test_email_send.py
git commit -m "feat(notifiers): SMTP sender with dry-run/fixture preview"
```

---

### Task 5: Sheet I/O wrappers (read month rows, scan, mark published)

**Files:**
- Modify: `src/sinks/sheets.py` (add four functions; relies on `select_publishable` from Task 2)

**Interfaces:**
- Consumes: `select_publishable` (Task 2); existing `_get_spreadsheet()`, `GOOGLE_SHEET_ID`.
- Produces:
  - `get_month_rows(month: str) -> list[dict]` — `get_all_records()` of the `YYYY-MM` tab, or `[]` if missing.
  - `month_tab_url(month: str) -> str` — deep link to that tab (`...#gid=<id>`), or the base spreadsheet URL if the tab is missing.
  - `get_rows_for_publishing() -> list[dict]` — across all `YYYY-MM` tabs, list of `{"tab": str, "row_number": int, "record": dict}` where `row_number` is the 1-based Sheet row (header is row 1, so `index + 2`).
  - `mark_published(targets: list[dict], ts: str) -> None` — write `ts` into column S for each target.

- [ ] **Step 1: Implement the wrappers**

This task is thin gspread glue over the already-tested pure helpers; it has no unit test (matching the repo convention that `append_rows` / `get_existing_intel_ids` are not unit-tested). Verification is import + lint + a real-Sheet dry run.

In `src/sinks/sheets.py`, add after `get_existing_intel_ids`:

```python
def get_month_rows(month: str) -> list[dict]:
    ss = _get_spreadsheet()
    try:
        ws = ss.worksheet(month)
    except gspread.exceptions.WorksheetNotFound:
        return []
    return ws.get_all_records()


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
        title = ws.title
        if not (len(title) == 7 and title[4] == "-"):
            continue
        records = ws.get_all_records()
        for i, rec in select_publishable(records):
            targets.append({"tab": title, "row_number": i + 2, "record": rec})
    return targets


def mark_published(targets: list[dict], ts: str) -> None:
    by_tab: dict[str, list[int]] = defaultdict(list)
    for t in targets:
        by_tab[t["tab"]].append(t["row_number"])
    ss = _get_spreadsheet()
    for tab, row_numbers in by_tab.items():
        ws = ss.worksheet(tab)
        ws.batch_update([{"range": f"S{rn}", "values": [[ts]]} for rn in row_numbers])
        log.info("Marked %d rows published in %s", len(row_numbers), tab)
```

`defaultdict` and `GOOGLE_SHEET_ID` are already imported at the top of `sheets.py`; no new imports needed.

- [ ] **Step 2: Verify import + lint**

Run: `uv run python -c "import src.sinks.sheets as s; print(s.get_month_rows, s.month_tab_url, s.get_rows_for_publishing, s.mark_published)"`
Expected: prints four function objects, no error.

Run: `uv run ruff check src/sinks/sheets.py`
Expected: `All checks passed!`

- [ ] **Step 3: Commit**

```bash
git add src/sinks/sheets.py
git commit -m "feat(sheets): month-row read, publish scan, mark_published writeback"
```

---

### Task 6: Wire new CLI modes into main.py

**Files:**
- Modify: `src/` import block, add two `stage_*` functions, and argparse in `main.py`

**Interfaces:**
- Consumes: `send_risk_digest`, `send_internal_announcement` (Task 4); `get_month_rows`, `month_tab_url`, `get_rows_for_publishing`, `mark_published`, `select_relevant` (Tasks 2/5); `USE_FIXTURE_DATA` (Task 1).
- Produces: `stage_notify_risk(month: str | None = None, dry_run: bool = False) -> int`; `stage_publish_internal(dry_run: bool = False) -> int`; CLI flags `--notify-risk`, `--publish-internal`, `--month`.

- [ ] **Step 1: Extend imports**

In `main.py`, replace the `from src.sinks.sheets import (...)` block with:

```python
from src.sinks.sheets import (
    append_rows,
    get_existing_intel_ids,
    get_month_rows,
    get_rows_for_publishing,
    load_assets_context,
    mark_published,
    month_tab_url,
    select_relevant,
)
```

Add these imports below the existing `from src.sinks...` imports:

```python
from src.config import USE_FIXTURE_DATA
from src.notifiers.email import send_internal_announcement, send_risk_digest
```

- [ ] **Step 2: Add the two stage functions**

In `main.py`, add after `stage_write_sheet` (before `def run(`):

```python
def stage_notify_risk(month: str | None = None, dry_run: bool = False) -> int:
    month = month or datetime.now(_TW).strftime("%Y-%m")
    records = get_month_rows(month)
    relevant = select_relevant(records)
    if not relevant:
        log.info("No company-relevant intel for %s, skipping risk digest", month)
        return 0
    sheet_url = month_tab_url(month)
    ok = send_risk_digest(month, relevant, sheet_url, dry_run=dry_run)
    log.info("Risk digest for %s: %d items, sent=%s", month, len(relevant), ok)
    return len(relevant) if ok else 0


def stage_publish_internal(dry_run: bool = False) -> int:
    targets = get_rows_for_publishing()
    if not targets:
        log.info("No approved intel to publish")
        return 0
    records = [t["record"] for t in targets]
    ok = send_internal_announcement(records, dry_run=dry_run)
    if ok and not dry_run and not USE_FIXTURE_DATA:
        ts = datetime.now(_TW).strftime("%Y-%m-%d %H:%M:%S")
        mark_published(targets, ts)
    log.info("Internal publish: %d approved items, sent=%s", len(targets), ok)
    return len(targets) if ok else 0
```

- [ ] **Step 3: Add argparse flags**

In `main()`, add after the `--list-data` argument:

```python
    parser.add_argument(
        "--notify-risk",
        action="store_true",
        help="寄送當月風險小組月會彙整信（Stage 4a）",
    )
    parser.add_argument(
        "--publish-internal",
        action="store_true",
        help="掃描 Sheet 已核可情資並發佈給 RD 主管（Stage 4b）",
    )
    parser.add_argument(
        "--month",
        type=str,
        default=None,
        metavar="YYYY-MM",
        help="--notify-risk 的目標月份，預設當月",
    )
```

- [ ] **Step 4: Dispatch the new modes**

In `main()`, replace this existing block:

```python
    if args.list_data:
        cmd_list_data(args.source)
        return

    if not args.source:
        parser.error("--source is required")
    if args.source not in ("twcert", "cisa_kev"):
        parser.error(f"--source must be 'twcert' or 'cisa_kev' (got '{args.source}')")

    try:
        run(
            source=args.source,
            dry_run=args.dry_run,
            since_date=args.since,
            save_data=args.save_data,
            load_data=args.load_data,
            fetch_only=args.fetch_only,
            analyze_only=args.analyze_only,
            load_analysis_path=args.load_analysis,
            limit=args.limit,
        )
    except TwcertLoginError:
```

with:

```python
    if args.list_data:
        cmd_list_data(args.source)
        return

    if not (args.notify_risk or args.publish_internal):
        if not args.source:
            parser.error("--source is required")
        if args.source not in ("twcert", "cisa_kev"):
            parser.error(f"--source must be 'twcert' or 'cisa_kev' (got '{args.source}')")

    try:
        if args.publish_internal:
            stage_publish_internal(dry_run=args.dry_run)
        elif args.notify_risk:
            stage_notify_risk(month=args.month, dry_run=args.dry_run)
        else:
            run(
                source=args.source,
                dry_run=args.dry_run,
                since_date=args.since,
                save_data=args.save_data,
                load_data=args.load_data,
                fetch_only=args.fetch_only,
                analyze_only=args.analyze_only,
                load_analysis_path=args.load_analysis,
                limit=args.limit,
            )
    except TwcertLoginError:
```

- [ ] **Step 5: Verify flags parse and existing tests pass**

Run: `uv run python main.py --help`
Expected: output includes `--notify-risk`, `--publish-internal`, and `--month`.

Run: `uv run pytest tests/ -v`
Expected: all tests PASS (existing + new from Tasks 1–4).

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: `All checks passed!` (format may need `uv run ruff format .` first)

Note: a full `--publish-internal` / `--notify-risk` run reads the live Sheet and needs Google credentials; that is a deployment verification, not a local unit test.

- [ ] **Step 6: Commit**

```bash
git add main.py
git commit -m "feat(main): --notify-risk and --publish-internal CLI modes"
```

---

### Task 7: GitHub Actions workflows

**Files:**
- Create: `.github/workflows/notify_risk.yml`
- Create: `.github/workflows/publish_internal.yml`

**Interfaces:**
- Consumes: the `--notify-risk` / `--publish-internal` CLI modes (Task 6) and the email/Sheet secrets.

- [ ] **Step 1: Create notify_risk.yml**

Create `.github/workflows/notify_risk.yml`:

```yaml
name: 風險小組月會彙整
on:
  schedule:
    - cron: '0 1 1 * *'  # 每月 1 號 09:00 TW+8
  workflow_dispatch:
    inputs:
      month:
        description: 'Target month YYYY-MM (TW+8). Defaults to current month.'
        required: false
        default: ''

jobs:
  notify:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@df4cb1c069e1874edd31b4311f1884172cec0e10  # v6
      - uses: astral-sh/setup-uv@37802adc94f370d6bfd71619e3f0bf239e1f3b78  # v7
      - run: uv sync
      - name: Send risk-team monthly digest
        env:
          GOOGLE_SHEET_ID:    ${{ secrets.GOOGLE_SHEET_ID }}
          GOOGLE_SA_JSON_B64: ${{ secrets.GOOGLE_SA_JSON_B64 }}
          SMTP_HOST:          ${{ secrets.SMTP_HOST }}
          SMTP_PORT:          ${{ secrets.SMTP_PORT }}
          SMTP_USER:          ${{ secrets.SMTP_USER }}
          SMTP_PASSWORD:      ${{ secrets.SMTP_PASSWORD }}
          EMAIL_FROM:         ${{ secrets.EMAIL_FROM }}
          RISK_TEAM_EMAILS:   ${{ secrets.RISK_TEAM_EMAILS }}
          USE_FIXTURE_DATA:   'false'
        run: |
          MONTH="${{ inputs.month }}"
          if [ -n "$MONTH" ]; then
            uv run python main.py --notify-risk --month "$MONTH"
          else
            uv run python main.py --notify-risk
          fi
```

- [ ] **Step 2: Create publish_internal.yml**

Create `.github/workflows/publish_internal.yml`:

```yaml
name: 內部情資發佈
on:
  schedule:
    - cron: '0 1,5,9 * * 1-5'  # 平日 09:00 / 13:00 / 17:00 TW+8
  workflow_dispatch: {}

jobs:
  publish:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@df4cb1c069e1874edd31b4311f1884172cec0e10  # v6
      - uses: astral-sh/setup-uv@37802adc94f370d6bfd71619e3f0bf239e1f3b78  # v7
      - run: uv sync
      - name: Publish approved intel to RD managers
        env:
          GOOGLE_SHEET_ID:          ${{ secrets.GOOGLE_SHEET_ID }}
          GOOGLE_SA_JSON_B64:       ${{ secrets.GOOGLE_SA_JSON_B64 }}
          SMTP_HOST:                ${{ secrets.SMTP_HOST }}
          SMTP_PORT:                ${{ secrets.SMTP_PORT }}
          SMTP_USER:                ${{ secrets.SMTP_USER }}
          SMTP_PASSWORD:            ${{ secrets.SMTP_PASSWORD }}
          EMAIL_FROM:               ${{ secrets.EMAIL_FROM }}
          INTERNAL_ANNOUNCE_EMAILS: ${{ secrets.INTERNAL_ANNOUNCE_EMAILS }}
          USE_FIXTURE_DATA:         'false'
        run: uv run python main.py --publish-internal
```

- [ ] **Step 3: Verify YAML parses**

Run: `uv run python -c "import yaml,glob; [yaml.safe_load(open(f)) for f in glob.glob('.github/workflows/*.yml')]; print('ok')"`
Expected: `ok` (PyYAML ships transitively; if missing, validate by inspection that the two files mirror `twcert.yml` structure).

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/notify_risk.yml .github/workflows/publish_internal.yml
git commit -m "ci: monthly risk digest + internal publish workflows"
```

---

### Task 8: Docs + .env.example

**Files:**
- Modify: `.env.example`
- Modify: `docs/configuration.md`
- Modify: `docs/architecture.md`

**Interfaces:** none (documentation only).

- [ ] **Step 1: Append email env vars to .env.example**

Add to the end of `.env.example`:

```bash
# --- Email 發佈層 (Stage 4a 風險小組月信 / Stage 4b 內部發佈) ---
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=secbot@example.com
SMTP_PASSWORD=your-app-password
EMAIL_FROM=資安情資Bot <secbot@example.com>
RISK_TEAM_EMAILS=risk-a@example.com,risk-b@example.com
INTERNAL_ANNOUNCE_EMAILS=rd-managers@example.com
```

- [ ] **Step 2: Document the env vars in docs/configuration.md**

Add a section to `docs/configuration.md` describing each new var (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_FROM`, `RISK_TEAM_EMAILS`, `INTERNAL_ANNOUNCE_EMAILS`), noting: SMTP defaults to `smtp.gmail.com:587` (STARTTLS); recipients are comma-separated; in fixture mode email is not sent (preview HTML is written to `src/data/`).

- [ ] **Step 3: Document Stages 4a/4b in docs/architecture.md**

In `docs/architecture.md`: add `src/notifiers/` to the directory tree and subsystem section (`email.py` SMTP sender, `templates.py` HTML renderers); extend the "Pipeline stages" section to mention Stage 4a (`--notify-risk`, monthly, risk-team digest of `company_relevance≠無`) and Stage 4b (`--publish-internal`, scans `狀態=核可發佈 & 通知時間 空`, emails RD managers, stamps S「通知時間」). Note the N「狀態」dropdown now includes `核可發佈`.

- [ ] **Step 4: Verify and commit**

Run: `uv run pytest tests/ -v && uv run ruff check . && uv run ruff format --check .`
Expected: all green.

```bash
git add .env.example docs/configuration.md docs/architecture.md
git commit -m "docs: email publishing layer config + architecture"
```

---

## Self-Review

**Spec coverage:**
- §3 SMTP transport → Task 1 (config) + Task 4 (sender). ✓
- §3 reuse N「狀態」+「核可發佈」→ Task 2 dropdown + `select_publishable`. ✓
- §3 reuse S「通知時間」as published flag → Task 2 (`select_publishable` excludes non-blank) + Task 5 (`mark_published`) + Task 6 (stamp only when live). ✓
- §3 risk digest scope `relevance≠無` → Task 2 `select_relevant` + Task 6 `stage_notify_risk`. ✓
- §3 monthly cadence, decoupled → Task 6 standalone mode + Task 7 monthly cron. ✓
- §3 internal content = summary cards from current Sheet values → Task 3 `render_internal_cards` + Task 5 reads live records. ✓
- §3 internal audience = RD managers → `INTERNAL_ANNOUNCE_EMAILS` (Tasks 1/4/7). ✓
- §3 `src/notifiers/` package → Tasks 3/4. ✓
- §6 `get_month_rows`/`month_tab_url` + filter + send → Tasks 5/6. ✓
- §7 scan/render/send/stamp + idempotency + dry-run no-stamp → Tasks 5/6. ✓
- §9 env vars → Tasks 1/8. ✓
- §11 error handling (best-effort, `send_ops_alert`, no-stamp on failure) → Task 4 `_smtp_send` + Task 6 stamp guard. ✓
- §12 tests → Tasks 1/2/3/4. ✓
- §13 workflows → Task 7. ✓

**Placeholder scan:** No TBD/TODO; every code step shows full code. ✓

**Type consistency:** `select_relevant`/`select_publishable` (Task 2) signatures match their use in Tasks 5/6; `send_risk_digest(month, records, sheet_url, dry_run)` and `send_internal_announcement(records, dry_run)` consistent across Tasks 4/6; `get_rows_for_publishing` returns `{"tab","row_number","record"}` consumed identically by `mark_published` and `stage_publish_internal`. ✓
