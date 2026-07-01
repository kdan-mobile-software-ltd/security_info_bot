from src.models import AnalysisResult, IntelItem
from src.sinks.sheets import (
    _resolve_month_tab,
    build_monthly_row,
    build_pool_backfill,
    build_pool_raw_row,
    filter_monthly_pairs,
    relevance_label,
)


def test_resolve_month_tab_uses_slash():
    assert _resolve_month_tab("2026-06-15") == "2026/06"
    assert _resolve_month_tab("2026-01-01T00:00:00") == "2026/01"


def test_resolve_month_tab_blank_falls_back_to_current_month():
    tab = _resolve_month_tab("")
    assert len(tab) == 7 and tab[4] == "/" and tab[:4].isdigit() and tab[5:].isdigit()


def _intel(rid="TWISAC-202601-0001", title="Apache RCE 漏洞", date="2026-01-15"):
    return IntelItem(
        intel_id=rid, source="TWCERT", publish_date=date, title=title, intel_type="101"
    )


def _analysis(relevance="H", reco="升級版本", assets=None, unit="資訊組"):
    return AnalysisResult(
        risk_level="High",
        summary="s",
        recommendation=reco,
        company_relevance=relevance,
        affected_assets=["對外 Web"] if assets is None else assets,
        responsible_unit=unit,
    )


def test_relevance_label_maps_hml():
    assert relevance_label("H") == "高相關"
    assert relevance_label("M") == "中相關"
    assert relevance_label("L") == "低相關"
    assert relevance_label("無") == "無"


def test_relevance_label_passthrough_unmapped():
    # A manual risk-team escalation label is left untouched.
    assert relevance_label("重大相關") == "重大相關"


def test_build_pool_raw_row_fills_only_intake_columns():
    row = build_pool_raw_row(_intel(), record_date="2026-01-22")
    assert row == [
        "2026-01-22",
        "TWISAC-202601-0001",
        "2026-01-15",
        "Apache RCE 漏洞",
        "",
        "",
        "",
        "",
    ]
    assert len(row) == 8  # A–H; analysis columns E–H blank until backfill


def test_build_pool_backfill_analysis_columns():
    row = build_pool_backfill(_analysis(relevance="M", reco="升級", assets=["A", "B"], unit="RD"))
    assert row == ["升級", "中相關", "A, B", "RD"]


def test_build_monthly_row_shape_status_and_labels():
    row = build_monthly_row(_intel(), _analysis(relevance="H"))
    assert row == [
        "TWISAC-202601-0001",
        "2026-01-15",
        "Apache RCE 漏洞",
        "升級版本",
        "高相關",
        "對外 Web",
        "資訊組",
        "",  # 追蹤表單連結
        "待處理",  # 狀態
        "",  # 通知時間
    ]
    assert len(row) == 10  # A–J


def test_build_pool_backfill_appends_ioc_url():
    row = build_pool_backfill(_analysis(reco="升級"), ioc_url="https://x/ioc_TEST.txt")
    assert row[0].startswith("升級")
    assert "IoC 清單：https://x/ioc_TEST.txt" in row[0]


def test_build_monthly_row_appends_ioc_url():
    row = build_monthly_row(_intel(), _analysis(), ioc_url="https://x/ioc_TEST.txt")
    assert "升級版本" in row[3]
    assert "IoC 清單：https://x/ioc_TEST.txt" in row[3]


def test_builders_no_ioc_url_leave_recommendation_unchanged():
    assert build_pool_backfill(_analysis(reco="只有建議"))[0] == "只有建議"
    assert build_monthly_row(_intel(), _analysis(reco="只有建議"))[3] == "只有建議"


def test_filter_monthly_pairs_excludes_none_relevance():
    pairs = [
        (_intel("a"), _analysis(relevance="H")),
        (_intel("b"), _analysis(relevance="無")),
        (_intel("c"), _analysis(relevance="L")),
    ]
    kept = [i.intel_id for i, _ in filter_monthly_pairs(pairs)]
    assert kept == ["a", "c"]
