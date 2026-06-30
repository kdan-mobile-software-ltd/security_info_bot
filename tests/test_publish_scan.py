from src.sinks.sheets import select_publishable, select_relevant


def _rec(rid, relevance="H", status="待處理", notified=""):
    return {
        "情資ID": rid,
        "標題": f"title-{rid}",
        "公司相關性": relevance,
        "狀態": status,
        "通知時間": notified,
    }


def test_select_relevant_excludes_none_and_blank():
    records = [
        _rec("a", relevance="H"),
        _rec("b", relevance="無"),
        _rec("c", relevance=""),
        _rec("d", relevance="M"),
    ]
    kept = [r["情資ID"] for r in select_relevant(records)]
    assert kept == ["a", "d"]


def test_select_publishable_only_approved_and_unsent():
    records = [
        _rec("a", status="核可發佈", notified=""),        # selected
        _rec("b", status="核可發佈", notified="2026-06-30"),  # already sent
        _rec("c", status="待處理", notified=""),           # not approved
        _rec("d", status="核可發佈", notified=""),         # selected
    ]
    picked = select_publishable(records)
    assert [(i, r["情資ID"]) for i, r in picked] == [(0, "a"), (3, "d")]
