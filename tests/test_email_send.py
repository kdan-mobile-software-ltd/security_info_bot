from unittest.mock import MagicMock

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
    ok = email_mod.send_risk_digest(
        "2026-06", [{"標題": "重大漏洞測試"}], "https://u", dry_run=True
    )
    assert ok is True
    previews = list(tmp_path.glob("email_preview_risk_*.html"))
    assert previews
    assert "重大漏洞測試" in previews[0].read_text(encoding="utf-8")


def test_fixture_mode_skips_smtp(tmp_path, monkeypatch):
    """USE_FIXTURE_DATA=True must preview + return True WITHOUT reaching SMTP,
    even when dry_run=False.
    """
    smtp_stub = MagicMock(
        side_effect=AssertionError("_smtp_send must not be called in fixture mode")
    )
    monkeypatch.setattr(email_mod, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(email_mod, "USE_FIXTURE_DATA", True)
    monkeypatch.setattr(email_mod, "_smtp_send", smtp_stub)

    ok = email_mod.send_internal_announcement(
        [{"標題": "fixture-test", "風險等級": "Critical"}], dry_run=False
    )

    assert ok is True
    previews = list(tmp_path.glob("email_preview_internal_*.html"))
    assert previews, "fixture mode must write a preview file"
    smtp_stub.assert_not_called()
