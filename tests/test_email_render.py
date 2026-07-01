from src.notifiers.templates import render_internal_cards, render_risk_digest


def _rec(
    rid="X1",
    content="Apache RCE 漏洞",
    relevance="高相關",
    reco="升級版本",
    assets="對外 Web",
    unit="資訊組",
):
    return {
        "情資編號": rid,
        "情資內容": content,
        "相關性": relevance,
        "建議措施": reco,
        "受影響資產": assets,
        "負責單位": unit,
    }


def test_risk_digest_contains_key_fields_and_link():
    html = render_risk_digest("2026/06", [_rec()], "https://sheet/url#gid=1")
    assert "2026/06" in html
    assert "Apache RCE 漏洞" in html
    assert "高相關" in html
    assert "https://sheet/url#gid=1" in html
    assert "核可發佈" in html  # instructs the team how to approve


def test_internal_cards_contains_key_fields():
    html = render_internal_cards([_rec()])
    assert "Apache RCE 漏洞" in html
    assert "高相關" in html
    assert "升級版本" in html
    assert "資訊組" in html


def test_renderers_escape_html():
    html = render_internal_cards([_rec(content="<script>x</script>")])
    assert "<script>x</script>" not in html
    assert "&lt;script&gt;" in html


def test_template_keys_are_exposed_monthly_keys():
    """The keys the templates read must be part of the position-based monthly
    dict keys, so a header/position change can't silently blank a column."""
    from src.sinks.sheets import MONTHLY_KEYS

    used = {"情資編號", "情資內容", "相關性", "建議措施", "受影響資產", "負責單位"}
    assert used <= set(MONTHLY_KEYS), used - set(MONTHLY_KEYS)
