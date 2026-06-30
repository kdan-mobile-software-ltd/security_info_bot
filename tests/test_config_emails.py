from src.config import parse_emails


def test_parse_emails_splits_and_strips():
    assert parse_emails("a@co, b@co ,c@co") == ["a@co", "b@co", "c@co"]


def test_parse_emails_empty_returns_empty_list():
    assert parse_emails("") == []
    assert parse_emails(None) == []


def test_parse_emails_drops_blank_segments():
    assert parse_emails("a@co,,") == ["a@co"]
