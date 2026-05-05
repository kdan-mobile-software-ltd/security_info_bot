import tempfile
from pathlib import Path

from openpyxl import Workbook

from src.parsers.ioc_xlsx import download_and_parse_ioc_xlsx, write_ioc_txt, IP_PATTERN


def _create_test_xlsx(ips: list[str]) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.append(["IP Address", "Description"])
    for ip in ips:
        ws.append([ip, "malicious"])
    path = Path(tempfile.gettempdir()) / "test_ioc.xlsx"
    wb.save(path)
    return path


def test_ip_pattern():
    assert IP_PATTERN.findall("192.168.1.1") == ["192.168.1.1"]
    assert IP_PATTERN.findall("10.0.0.1 and 172.16.0.1") == ["10.0.0.1", "172.16.0.1"]
    assert IP_PATTERN.findall("999.999.999.999") == []
    assert IP_PATTERN.findall("no ip here") == []


def test_parse_ioc_xlsx_local():
    test_ips = ["192.168.1.1", "10.0.0.50", "172.16.0.100"]
    xlsx_path = _create_test_xlsx(test_ips)

    from unittest.mock import patch, MagicMock

    mock_resp = MagicMock()
    mock_resp.content = xlsx_path.read_bytes()
    mock_resp.raise_for_status = MagicMock()

    with patch("src.parsers.ioc_xlsx.requests.get", return_value=mock_resp):
        result = download_and_parse_ioc_xlsx("https://example.com/test.xlsx", "TEST-001")

    assert result is not None
    content = result.read_text()
    for ip in test_ips:
        assert ip in content

    result.unlink(missing_ok=True)
    xlsx_path.unlink(missing_ok=True)


def test_parse_ioc_xlsx_no_ips():
    wb = Workbook()
    ws = wb.active
    ws.append(["Name", "Description"])
    ws.append(["test", "no ip"])
    path = Path(tempfile.gettempdir()) / "test_no_ip.xlsx"
    wb.save(path)

    from unittest.mock import patch, MagicMock

    mock_resp = MagicMock()
    mock_resp.content = path.read_bytes()
    mock_resp.raise_for_status = MagicMock()

    with patch("src.parsers.ioc_xlsx.requests.get", return_value=mock_resp):
        result = download_and_parse_ioc_xlsx("https://example.com/empty.xlsx", "TEST-002")

    assert result is None
    path.unlink(missing_ok=True)


def test_write_ioc_txt_dedupes_and_sorts():
    path = write_ioc_txt("TWISAC-001/A", ["10.0.0.2", "10.0.0.1", "10.0.0.2", ""])
    assert path is not None
    content = path.read_text()
    assert content == "10.0.0.1\n10.0.0.2\n"
    assert "TWISAC-001_A" in path.name
    path.unlink(missing_ok=True)


def test_write_ioc_txt_empty_returns_none():
    assert write_ioc_txt("TWISAC-002", []) is None
    assert write_ioc_txt("TWISAC-002", [""]) is None
