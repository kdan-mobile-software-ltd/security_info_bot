from src.notifiers.templates import render_internal_cards, render_risk_digest


def _rec(
    rid="X1",
    title="Apache RCE",
    risk="Critical",
    relevance="H",
    cve="CVE-2024-1\nCVE-2024-2",
    summary="摘要內容",
    reco="升級版本",
    assets="對外 Web",
    source="TWCERT",
):
    return {
        "情資ID": rid,
        "標題": title,
        "風險等級": risk,
        "公司相關性": relevance,
        "CVE ID": cve,
        "摘要": summary,
        "建議措施": reco,
        "受影響資產": assets,
        "來源": source,
    }


def test_risk_digest_contains_key_fields_and_link():
    html = render_risk_digest("2026-06", [_rec()], "https://sheet/url#gid=1")
    assert "2026-06" in html
    assert "Apache RCE" in html
    assert "Critical" in html
    assert "https://sheet/url#gid=1" in html
    assert "核可發佈" in html  # instructs the team how to approve


def test_internal_cards_contains_key_fields():
    html = render_internal_cards([_rec()])
    assert "Apache RCE" in html
    assert "Critical" in html
    assert "摘要內容" in html
    assert "升級版本" in html


def test_renderers_escape_html():
    html = render_internal_cards([_rec(title="<script>x</script>")])
    assert "<script>x</script>" not in html
    assert "&lt;script&gt;" in html


def test_template_and_selector_keys_are_real_headers():
    from src.sinks.sheets import INTEL_HEADERS

    used = {
        "情資ID",
        "標題",
        "風險等級",
        "公司相關性",
        "CVE ID",
        "摘要",
        "建議措施",
        "受影響資產",
        "來源",
        "狀態",
        "通知時間",
    }
    assert used <= set(INTEL_HEADERS), used - set(INTEL_HEADERS)
