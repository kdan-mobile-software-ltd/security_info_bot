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
