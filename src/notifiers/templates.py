from __future__ import annotations

from html import escape


def _cell(value: object) -> str:
    return escape(str(value if value is not None else ""))


def render_risk_digest(month: str, records: list[dict], sheet_url: str) -> str:
    rows = []
    for r in records:
        rows.append(
            "<tr>"
            f"<td>{_cell(r.get('情資編號'))}</td>"
            f"<td>{_cell(r.get('情資內容'))}</td>"
            f"<td>{_cell(r.get('相關性'))}</td>"
            f"<td>{_cell(r.get('建議措施'))}</td>"
            f"<td>{_cell(r.get('受影響資產'))}</td>"
            f"<td>{_cell(r.get('負責單位'))}</td>"
            "</tr>"
        )
    body = "".join(rows)
    return (
        "<html><body>"
        f"<h2>{_cell(month)} 資安情資月會彙整（{len(records)} 筆與公司相關）</h2>"
        f'<p>請於月會中至 <a href="{_cell(sheet_url)}">Google Sheet（{_cell(month)}）</a> '
        "檢視與修改，並將要對外公告者「狀態」設為「核可發佈」。</p>"
        '<table border="1" cellpadding="6" cellspacing="0">'
        "<tr><th>情資編號</th><th>情資內容</th><th>相關性</th>"
        "<th>建議措施</th><th>受影響資產</th><th>負責單位</th></tr>"
        f"{body}</table></body></html>"
    )


def render_internal_cards(records: list[dict]) -> str:
    cards = []
    for r in records:
        cards.append(
            '<div style="border:1px solid #ccc;border-radius:8px;padding:12px;margin:12px 0">'
            f"<h3>{_cell(r.get('情資內容'))}</h3>"
            f"<p><b>情資編號：</b>{_cell(r.get('情資編號'))}　"
            f"<b>相關性：</b>{_cell(r.get('相關性'))}</p>"
            f"<p><b>建議措施：</b>{_cell(r.get('建議措施'))}</p>"
            f"<p><b>受影響資產：</b>{_cell(r.get('受影響資產'))}</p>"
            f"<p><b>負責單位：</b>{_cell(r.get('負責單位'))}</p>"
            "</div>"
        )
    body = "".join(cards)
    return f"<html><body><h2>資安情資公告（{len(records)} 筆）</h2>{body}</body></html>"
