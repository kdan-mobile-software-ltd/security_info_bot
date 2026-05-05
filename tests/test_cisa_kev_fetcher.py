import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.fetchers.cisa_kev import fetch_cisa_kev

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def mock_cisa_response():
    with open(FIXTURES_DIR / "sample_cisa_kev.json", encoding="utf-8") as f:
        return json.load(f)


def test_fetch_cisa_kev_filters_by_date(mock_cisa_response):
    mock_resp = MagicMock()
    mock_resp.json.return_value = mock_cisa_response
    mock_resp.raise_for_status = MagicMock()

    with patch("src.fetchers.cisa_kev.requests.get", return_value=mock_resp):
        items = fetch_cisa_kev(target_date="2024-04-15")

    assert len(items) == 2
    ids = {item.intel_id for item in items}
    assert "CVE-2024-12345" in ids
    assert "CVE-2024-67890" in ids
    assert "CVE-2024-11111" not in ids


def test_fetch_cisa_kev_no_matches(mock_cisa_response):
    mock_resp = MagicMock()
    mock_resp.json.return_value = mock_cisa_response
    mock_resp.raise_for_status = MagicMock()

    with patch("src.fetchers.cisa_kev.requests.get", return_value=mock_resp):
        items = fetch_cisa_kev(target_date="2099-01-01")

    assert len(items) == 0


def test_cisa_kev_item_structure(mock_cisa_response):
    mock_resp = MagicMock()
    mock_resp.json.return_value = mock_cisa_response
    mock_resp.raise_for_status = MagicMock()

    with patch("src.fetchers.cisa_kev.requests.get", return_value=mock_resp):
        items = fetch_cisa_kev(target_date="2024-04-15")

    apache_item = next(i for i in items if i.intel_id == "CVE-2024-12345")
    assert apache_item.source == "CISA_KEV"
    assert apache_item.publish_date == "2024-04-15"
    assert "Apache" in apache_item.title
    assert apache_item.cve_ids == ["CVE-2024-12345"]
    assert apache_item.intel_type == "101-漏洞訊息"
    assert any("nvd.nist.gov" in url for url in apache_item.reference_urls)
    assert "Known" in apache_item.raw_content
