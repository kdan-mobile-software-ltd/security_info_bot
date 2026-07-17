import json

import pytest

import main
from src.monitors import staleness as st


class _Recorder:
    """Capture what the check would persist / send, replacing the real sinks."""

    def __init__(self):
        self.commits: list[dict] = []
        self.alerts: list[tuple[str, str, bool]] = []

    def commit_files(self, files, message, archive_dir=None):
        path = files[0]
        self.commits.append(
            {
                "state": json.loads(path.read_text(encoding="utf-8")),
                "name": path.name,
                "message": message,
                "archive_dir": archive_dir,
            }
        )

    def send_ops_email(self, title, detail, dry_run=False):
        self.alerts.append((title, detail, dry_run))
        return True

    @property
    def persisted(self) -> dict:
        assert self.commits, "expected state to be persisted"
        return self.commits[-1]["state"]


@pytest.fixture
def rec(tmp_path, monkeypatch):
    r = _Recorder()
    monkeypatch.setattr(st, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(st, "commit_files", r.commit_files)
    monkeypatch.setattr(st, "send_ops_email", r.send_ops_email)
    monkeypatch.setattr(st, "TWCERT_STALE_DAYS", 7)
    # Tests inherit USE_FIXTURE_DATA=true (the config default), which forces the
    # dry-run path. Pin it off so these exercise the real production behaviour;
    # test_fixture_mode_never_records_an_alert_as_sent covers the on case.
    monkeypatch.setattr(st, "USE_FIXTURE_DATA", False)
    return r


def _state(raw, monkeypatch):
    """Make read_archive_file return raw (a str, or None for 'no state')."""
    monkeypatch.setattr(st, "read_archive_file", lambda relpath: raw)


def _json_state(last_total, last_changed, alerted):
    return json.dumps({"last_total": last_total, "last_changed": last_changed, "alerted": alerted})


def test_no_prior_state_initializes_without_alert(rec, monkeypatch):
    _state(None, monkeypatch)

    st.check_twcert_staleness(844, "2026-07-17")

    assert rec.alerts == []
    assert rec.persisted == {"last_total": 844, "last_changed": "2026-07-17", "alerted": False}
    assert rec.commits[-1]["name"] == "_fetch_state.json"
    assert rec.commits[-1]["archive_dir"] == "twcert"


def test_total_changed_resets_streak_without_alert(rec, monkeypatch):
    # Quiet for 30 days AND already alerted — a new item must still reset cleanly.
    _state(_json_state(844, "2026-06-17", True), monkeypatch)

    st.check_twcert_staleness(845, "2026-07-17")

    assert rec.alerts == []
    assert rec.persisted == {"last_total": 845, "last_changed": "2026-07-17", "alerted": False}


def test_unchanged_below_threshold_does_not_alert(rec, monkeypatch):
    _state(_json_state(844, "2026-07-11", False), monkeypatch)  # 6 days

    st.check_twcert_staleness(844, "2026-07-17")

    assert rec.alerts == []
    assert rec.commits == [], "nothing changed; no need to rewrite state"


def test_unchanged_at_threshold_alerts_once_and_persists_flag(rec, monkeypatch):
    _state(_json_state(844, "2026-07-10", False), monkeypatch)  # exactly 7 days

    st.check_twcert_staleness(844, "2026-07-17")

    assert len(rec.alerts) == 1
    title, detail, dry_run = rec.alerts[0]
    assert "7" in title
    assert "844" in detail and "2026-07-10" in detail
    assert dry_run is False
    # last_changed must stay pinned to the real last-change date, not today.
    assert rec.persisted == {"last_total": 844, "last_changed": "2026-07-10", "alerted": True}


def test_already_alerted_does_not_alert_again(rec, monkeypatch):
    _state(_json_state(844, "2026-07-01", True), monkeypatch)  # 16 days, alerted

    st.check_twcert_staleness(844, "2026-07-17")

    assert rec.alerts == []
    assert rec.commits == []


def test_dry_run_neither_commits_nor_sends_real_email(rec, monkeypatch):
    _state(_json_state(844, "2026-07-10", False), monkeypatch)

    st.check_twcert_staleness(844, "2026-07-17", dry_run=True)

    assert len(rec.alerts) == 1
    assert rec.alerts[0][2] is True, "dry_run must be passed through to send_ops_email"
    assert rec.commits == [], "dry run must not commit state"


def test_fixture_mode_never_records_an_alert_as_sent(rec, monkeypatch):
    """Fixture mode previews instead of sending, and send_ops_email still returns True.

    Persisting alerted=True off that would let a local `--fetch-only` run (which is
    NOT --dry-run, and which .env.example points at the shared data branch) suppress
    the real production alert for the whole quiet stretch.
    """
    monkeypatch.setattr(st, "USE_FIXTURE_DATA", True)
    _state(_json_state(844, "2026-07-10", False), monkeypatch)

    st.check_twcert_staleness(844, "2026-07-17", dry_run=False)

    assert rec.alerts and rec.alerts[0][2] is True, "fixture mode must force dry_run"
    assert rec.commits == [], "fixture mode must not persist state"


def test_corrupt_state_is_treated_as_missing(rec, monkeypatch):
    _state("{not valid json", monkeypatch)

    st.check_twcert_staleness(844, "2026-07-17")

    assert rec.alerts == []
    assert rec.persisted == {"last_total": 844, "last_changed": "2026-07-17", "alerted": False}


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param({"last_total": 844, "last_changed": "07/17/2026"}, id="bad-date-format"),
        pytest.param({"last_total": "844", "last_changed": "2026-07-10"}, id="total-not-int"),
        pytest.param({"last_total": None, "last_changed": "2026-07-10"}, id="total-null"),
    ],
)
def test_unusable_state_values_are_repaired_not_looped_forever(rec, monkeypatch, bad):
    """Garbage values must re-initialize the file.

    Letting _to_date raise into the blanket handler would return without repairing,
    so every later run would hit the same garbage and the alert could never fire.
    """
    _state(json.dumps(bad), monkeypatch)

    st.check_twcert_staleness(844, "2026-07-17")

    assert rec.alerts == []
    assert rec.persisted == {"last_total": 844, "last_changed": "2026-07-17", "alerted": False}


def test_unreadable_state_must_not_reset_the_streak(rec, monkeypatch):
    """read_archive_file raises on IO failure; that must not look like a first run.

    Treating it as 'no state' would rewrite last_changed=today mid-stretch and
    silently cancel the pending alert.
    """

    def boom(relpath):
        raise OSError("worktree vanished")

    monkeypatch.setattr(st, "read_archive_file", boom)

    st.check_twcert_staleness(836, "2026-07-16")

    assert rec.alerts == []
    assert rec.commits == [], "a failed read must leave the existing streak alone"


def test_state_missing_keys_is_treated_as_missing(rec, monkeypatch):
    _state(json.dumps({"unexpected": 1}), monkeypatch)

    st.check_twcert_staleness(844, "2026-07-17")

    assert rec.alerts == []
    assert rec.persisted["last_total"] == 844


def test_dependency_exception_is_swallowed(rec, monkeypatch):
    def boom(relpath):
        raise RuntimeError("archive worktree exploded")

    monkeypatch.setattr(st, "read_archive_file", boom)

    st.check_twcert_staleness(844, "2026-07-17")  # must not raise

    assert rec.alerts == []
    assert rec.commits == []


def test_email_failure_does_not_break_pipeline(rec, monkeypatch):
    _state(_json_state(844, "2026-07-10", False), monkeypatch)

    def boom(title, detail, dry_run=False):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(st, "send_ops_email", boom)

    st.check_twcert_staleness(844, "2026-07-17")  # must not raise

    assert rec.commits == [], "alert never went out, so the alerted flag must not be persisted"


def test_undelivered_alert_is_not_recorded_as_sent(rec, monkeypatch):
    """_smtp_send returns False (no recipients / SMTP refused) instead of raising.

    Persisting alerted=True on that path would suppress every future retry for the
    whole quiet stretch — including after OPS_ALERT_EMAILS is finally configured.
    """
    _state(_json_state(844, "2026-07-10", False), monkeypatch)
    monkeypatch.setattr(st, "send_ops_email", lambda title, detail, dry_run=False: False)

    st.check_twcert_staleness(844, "2026-07-17")

    assert rec.commits == [], "undelivered alert must not persist alerted=True"


def test_retry_after_undelivered_alert_still_alerts(rec, monkeypatch):
    """The day after a failed send, the alert must fire again (state was left alone)."""
    _state(_json_state(844, "2026-07-10", False), monkeypatch)

    st.check_twcert_staleness(844, "2026-07-18")  # 8 days, still not alerted

    assert len(rec.alerts) == 1
    assert rec.persisted["alerted"] is True


def test_stage_fetch_threads_dry_run_not_save(tmp_path, monkeypatch):
    """--dry-run must not email, even though `save` stays True.

    `save` only controls archiving the fetched items, so deriving the alert's
    dry_run from it would send real mail during a --dry-run.
    """
    seen: list[bool] = []
    monkeypatch.setattr(main, "fetch_twcert", lambda since, limit=None: ([], 844))
    monkeypatch.setattr(
        main,
        "check_twcert_staleness",
        lambda total, day, dry_run=False: seen.append(dry_run),
    )
    monkeypatch.setattr(main, "save_items", lambda *a, **k: tmp_path / "x.json")
    monkeypatch.setattr(main, "commit_files", lambda *a, **k: None)

    main.stage_fetch("twcert", since_date="2026-07-17", save=True, dry_run=True)
    main.stage_fetch("twcert", since_date="2026-07-17", save=True, dry_run=False)

    assert seen == [True, False]
