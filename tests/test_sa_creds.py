from src.config import get_service_account_path


def test_sa_path_none_when_unset(monkeypatch):
    """No SA env → None, so callers fall back to ADC (Cloud Run SA)."""
    monkeypatch.delenv("GOOGLE_SA_JSON_B64", raising=False)
    monkeypatch.delenv("GOOGLE_SA_JSON_FILE", raising=False)
    assert get_service_account_path() is None


def test_sa_path_returns_existing_file(tmp_path, monkeypatch):
    f = tmp_path / "sa.json"
    f.write_text("{}")
    monkeypatch.delenv("GOOGLE_SA_JSON_B64", raising=False)
    monkeypatch.setenv("GOOGLE_SA_JSON_FILE", str(f))
    assert get_service_account_path() == str(f)


def test_sa_path_ignores_missing_file(monkeypatch):
    """A GOOGLE_SA_JSON_FILE pointing at a non-existent path is ignored → None."""
    monkeypatch.delenv("GOOGLE_SA_JSON_B64", raising=False)
    monkeypatch.setenv("GOOGLE_SA_JSON_FILE", "/no/such/sa.json")
    assert get_service_account_path() is None
