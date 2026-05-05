from datetime import datetime, timezone, timedelta

from src.fetchers.twcert import _filter_and_check_cutoff, _since_to_epoch_ms

_TW = timezone(timedelta(hours=8))


def _entry(date_str: str) -> dict:
    """Build a minimal list entry with publishDate at Taiwan midnight for the given YYYY-MM-DD."""
    epoch_ms = _since_to_epoch_ms(date_str)
    return {"infoId": date_str, "publishDate": epoch_ms}


def test_since_to_epoch_ms_is_taiwan_midnight():
    ms = _since_to_epoch_ms("2026-05-05")
    expected = datetime(2026, 5, 5, 0, 0, tzinfo=_TW).timestamp() * 1000
    assert ms == expected
    # Sanity: round-tripping back gives the same date string
    assert datetime.fromtimestamp(ms / 1000, tz=_TW).strftime("%Y-%m-%d") == "2026-05-05"


def test_filter_keeps_items_on_or_after_cutoff():
    cutoff = _since_to_epoch_ms("2026-05-04")
    entries = [_entry("2026-05-05"), _entry("2026-05-04"), _entry("2026-05-03")]
    kept, stop = _filter_and_check_cutoff(entries, cutoff)
    assert [e["infoId"] for e in kept] == ["2026-05-05", "2026-05-04"]
    assert stop is True


def test_filter_no_cutoff_breach_does_not_stop():
    cutoff = _since_to_epoch_ms("2026-05-01")
    entries = [_entry("2026-05-05"), _entry("2026-05-04")]
    kept, stop = _filter_and_check_cutoff(entries, cutoff)
    assert len(kept) == 2
    assert stop is False


def test_filter_all_old_returns_empty_and_stops():
    cutoff = _since_to_epoch_ms("2026-05-05")
    entries = [_entry("2026-05-03"), _entry("2026-05-02")]
    kept, stop = _filter_and_check_cutoff(entries, cutoff)
    assert kept == []
    assert stop is True


def test_filter_missing_publish_date_is_kept():
    cutoff = _since_to_epoch_ms("2026-05-05")
    entry = {"infoId": "no-date", "publishDate": None}
    kept, stop = _filter_and_check_cutoff([entry], cutoff)
    assert len(kept) == 1
    assert stop is False
