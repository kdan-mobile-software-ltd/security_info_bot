from src.sinks.sheets import (
    MONTHLY_HEADERS,
    _month_rows_from_values,
    select_publishable,
    select_relevant,
)


def _rec(rid, relevance="高相關", status="待處理", notified=""):
    return {
        "情資編號": rid,
        "情資內容": f"content-{rid}",
        "相關性": relevance,
        "狀態": status,
        "通知時間": notified,
    }


def test_select_relevant_excludes_none_and_blank():
    records = [
        _rec("a", relevance="高相關"),
        _rec("b", relevance="無"),
        _rec("c", relevance=""),
        _rec("d", relevance="中相關"),
    ]
    kept = [r["情資編號"] for r in select_relevant(records)]
    assert kept == ["a", "d"]


def test_select_publishable_only_approved_and_unsent():
    records = [
        _rec("a", status="核可發佈", notified=""),  # selected
        _rec("b", status="核可發佈", notified="2026-06-30"),  # already sent
        _rec("c", status="待處理", notified=""),  # not approved
        _rec("d", status="核可發佈", notified=""),  # selected
    ]
    picked = select_publishable(records)
    assert [(i, r["情資編號"]) for i, r in picked] == [(0, "a"), (3, "d")]


def test_month_rows_from_values_reads_by_position():
    """狀態 lives at col I (idx8) and 通知時間 at col J (idx9); the human-only
    追蹤表單連結 (idx7) is skipped. Verify the position mapping, not header text."""
    values = [
        MONTHLY_HEADERS,
        [
            "ID-1",  # 情資編號 (A)
            "2026-06-01",  # 情資發布日期 (B)
            "內容",  # 情資內容 (C)
            "建議",  # 建議措施 (D)
            "高相關",  # 風險相關性 (E)
            "資產X",  # 內部受影響資產 (F)
            "資訊組",  # 處置措施負責單位 (G)
            "http://form",  # 追蹤表單連結 (H, skipped)
            "核可發佈",  # 狀態 (I)
            "",  # 通知時間 (J)
        ],
    ]
    rows = _month_rows_from_values(values)
    assert len(rows) == 1
    assert rows[0]["情資編號"] == "ID-1"
    assert rows[0]["相關性"] == "高相關"
    assert rows[0]["負責單位"] == "資訊組"
    assert rows[0]["狀態"] == "核可發佈"
    assert rows[0]["通知時間"] == ""
    # the row is publishable (approved + unsent)
    assert select_publishable(rows) == [(0, rows[0])]
