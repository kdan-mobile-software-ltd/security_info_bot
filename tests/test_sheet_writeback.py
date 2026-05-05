from unittest.mock import patch, MagicMock

from src.models import IntelItem, AnalysisResult, SheetRow


def test_sheet_row_from_intel_single_cve():
    intel = IntelItem(
        intel_id="TWISAC-202404-0001",
        source="TWCERT",
        publish_date="2024-04-15",
        title="Apache RCE 漏洞通報",
        intel_type="101-漏洞訊息",
        cve_ids=["CVE-2024-12345"],
        reference_urls=["https://nvd.nist.gov/vuln/detail/CVE-2024-12345"],
    )
    analysis = AnalysisResult(
        risk_level="Critical",
        summary="Apache HTTP Server 存在遠端程式碼執行漏洞",
        recommendation="升級至 2.4.59 以上",
        company_relevance="H",
        affected_assets=["對外 Web 服務"],
        responsible_unit="系統組",
    )

    row = SheetRow.from_intel_and_analysis(intel, analysis, "CVE-2024-12345")

    assert row.intel_id == "TWISAC-202404-0001"
    assert row.cve_id == "CVE-2024-12345"
    assert row.risk_level == "Critical"
    assert row.company_relevance == "H"
    assert row.status == "待處理"

    row_list = row.to_row_list()
    assert len(row_list) == 20


def test_sheet_row_multi_cve_suffix():
    intel = IntelItem(
        intel_id="TWISAC-202404-0002",
        source="TWCERT",
        publish_date="2024-04-15",
        title="多 CVE 情資",
        intel_type="101-漏洞訊息",
        cve_ids=["CVE-2024-1111", "CVE-2024-2222"],
    )
    analysis = AnalysisResult(
        risk_level="High",
        summary="test",
        recommendation="test",
        company_relevance="M",
    )

    row1 = SheetRow.from_intel_and_analysis(intel, analysis, "CVE-2024-1111", intel_id_suffix="1")
    row2 = SheetRow.from_intel_and_analysis(intel, analysis, "CVE-2024-2222", intel_id_suffix="2")

    assert row1.intel_id == "TWISAC-202404-0002-1"
    assert row2.intel_id == "TWISAC-202404-0002-2"
    assert row1.cve_id == "CVE-2024-1111"
    assert row2.cve_id == "CVE-2024-2222"


def test_sheet_row_with_ioc_link():
    intel = IntelItem(
        intel_id="TWISAC-202404-0003",
        source="TWCERT",
        publish_date="2024-04-15",
        title="IoC 封鎖清單",
        intel_type="IoC",
    )
    analysis = AnalysisResult(
        risk_level="High",
        summary="含 IP 封鎖清單",
        recommendation="匯入防火牆封鎖",
        company_relevance="H",
    )

    row = SheetRow.from_intel_and_analysis(
        intel, analysis, "",
        ioc_drive_link="https://drive.google.com/file/d/xxx/view",
    )

    assert "https://drive.google.com/file/d/xxx/view" in row.recommendation


def test_dedup_logic():
    existing = {"TWISAC-202404-0001", "CVE-2024-12345"}
    items = [
        IntelItem(intel_id="TWISAC-202404-0001", source="TWCERT", publish_date="", title="", intel_type=""),
        IntelItem(intel_id="TWISAC-202404-0099", source="TWCERT", publish_date="", title="", intel_type=""),
        IntelItem(intel_id="CVE-2024-12345", source="CISA_KEV", publish_date="", title="", intel_type=""),
    ]

    new_items = [item for item in items if item.intel_id not in existing]
    assert len(new_items) == 1
    assert new_items[0].intel_id == "TWISAC-202404-0099"
