from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from src.config import TWCERT_STALE_DAYS, USE_FIXTURE_DATA
from src.notifiers.email import send_ops_email
from src.sinks.git_archive import commit_files, read_archive_file
from src.utils.logging import log

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

_STATE_DIR = "twcert"
_STATE_NAME = "_fetch_state.json"
_STATE_RELPATH = f"{_STATE_DIR}/{_STATE_NAME}"


def _to_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _read_state() -> dict | None:
    """Return the parsed fetch state, or None when there is no usable state.

    Propagates read errors: read_archive_file returns None only for 'no state
    yet', so a failure to read must not be mistaken for a first run — that would
    silently reset the quiet streak and cancel a pending alert.

    Unusable *content* (corrupt JSON, missing keys, wrong types, unparseable
    date) returns None on purpose: the file is garbage and would stay garbage,
    so the caller re-initializes it rather than blocking on it forever.
    """
    raw = read_archive_file(_STATE_RELPATH)
    if not raw:
        return None
    try:
        state = json.loads(raw)
    except ValueError as e:
        log.warning("staleness: corrupt state file %s: %s", _STATE_RELPATH, e)
        return None
    if not isinstance(state, dict) or "last_total" not in state or "last_changed" not in state:
        log.warning("staleness: unusable state file %s (missing keys)", _STATE_RELPATH)
        return None
    if not isinstance(state["last_total"], int) or isinstance(state["last_total"], bool):
        log.warning("staleness: unusable state file %s (last_total not an int)", _STATE_RELPATH)
        return None
    try:
        _to_date(state["last_changed"])
    except (TypeError, ValueError) as e:
        log.warning("staleness: unusable state file %s (bad last_changed: %s)", _STATE_RELPATH, e)
        return None
    return state


def _write_state(server_total: int, last_changed: str, alerted: bool, dry_run: bool) -> None:
    state = {"last_total": server_total, "last_changed": last_changed, "alerted": alerted}
    if dry_run:
        log.info("[DRY RUN] Would persist twcert fetch state: %s", state)
        return
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = _DATA_DIR / _STATE_NAME
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    commit_files([path], "data(twcert): fetch state", archive_dir=_STATE_DIR)


def check_twcert_staleness(server_total: int, today: str, dry_run: bool = False) -> None:
    """Alert by email when TWCERT's total intel count has not moved for N days.

    today is the Taiwan date of the *run* (YYYY-MM-DD) — never the --since fetch
    window, which an operator can backdate: the server total is global and not
    date-filtered, so stamping it with a backfill's --since would fabricate a
    months-long quiet streak.  Each quiet stretch alerts only once.  Never
    raises: a monitoring check must not break the pipeline.
    """
    # Fixture mode makes send_ops_email return True from a local preview without
    # sending anything, so it must not be allowed to record an alert as delivered.
    dry_run = dry_run or USE_FIXTURE_DATA
    try:
        state = _read_state()

        if state is None:
            log.info(
                "staleness: no prior twcert state; initializing at total=%d (%s)",
                server_total,
                today,
            )
            _write_state(server_total, today, False, dry_run)
            return

        if server_total != state["last_total"]:
            log.info(
                "staleness: twcert total changed %s -> %d; resetting quiet streak",
                state["last_total"],
                server_total,
            )
            _write_state(server_total, today, False, dry_run)
            return

        last_changed = state["last_changed"]
        days = (_to_date(today) - _to_date(last_changed)).days

        if days < TWCERT_STALE_DAYS:
            log.info(
                "staleness: twcert total unchanged at %d for %d day(s) (threshold %d)",
                server_total,
                days,
                TWCERT_STALE_DAYS,
            )
            return

        if state.get("alerted"):
            log.info(
                "staleness: twcert quiet for %d day(s); alert already sent for this stretch",
                days,
            )
            return

        title = f"TWCERT 已連續 {days} 天無新情資"
        detail = (
            f"TWCERT 情資總數自 {last_changed} 起維持在 {server_total} 筆未變動，"
            f"至今 ({today}) 已連續 {days} 天沒有新情資。\n"
            f"告警門檻：TWCERT_STALE_DAYS={TWCERT_STALE_DAYS} 天。\n"
            "請確認 TWCERT 確實沒有發布新情資，或擷取流程（登入／列表 API）是否已失效。"
        )
        log.info("staleness: twcert quiet for %d day(s); sending ops alert", days)
        # Only record the alert as sent once it is actually delivered: _smtp_send
        # returns False (rather than raising) when delivery fails or no recipients
        # are configured, and a swallowed failure must not suppress tomorrow's retry.
        if not send_ops_email(title, detail, dry_run=dry_run):
            log.warning("staleness: ops alert not delivered; will retry on the next run")
            return
        _write_state(server_total, last_changed, True, dry_run)
    except Exception as e:
        log.warning("staleness check failed: %s", e)
