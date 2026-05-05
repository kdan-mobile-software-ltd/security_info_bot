from __future__ import annotations

from datetime import datetime

import requests

from src.config import MATTERMOST_WEBHOOK
from src.models import AnalysisResult, IntelItem
from src.utils.logging import log


def send_intel_alert(
    intel: IntelItem,
    analysis: AnalysisResult,
    cve_id: str,
    ioc_drive_link: str = "",
) -> str | None:
    if analysis.risk_level not in ("Critical", "High"):
        return None

    if not MATTERMOST_WEBHOOK:
        log.warning("MATTERMOST_WEBHOOK not set, skipping alert for %s", intel.intel_id)
        return None

    level_emoji = ":red_circle:" if analysis.risk_level == "Critical" else ":orange_circle:"

    text_parts = [
        f"### {level_emoji} [{analysis.risk_level}] 資安情資警報",
        f"**情資編號：** {intel.intel_id}",
        f"**來源：** {intel.source}",
        f"**標題：** {intel.title}",
        f"**CVE：** {cve_id}" if cve_id else "",
        f"**AI 風險等級：** {analysis.risk_level}",
        f"**AI 分析摘要：** {analysis.summary}",
        f"**建議措施：** {analysis.recommendation}",
        f"**公司風險相關性：** {analysis.company_relevance}",
        f"**受影響資產：** {', '.join(analysis.affected_assets)}" if analysis.affected_assets else "",
        f"**建議處置單位：** {analysis.responsible_unit}" if analysis.responsible_unit else "",
    ]

    if ioc_drive_link:
        text_parts.append(f"\n:shield: **IP 封鎖清單下載：** [點此下載]({ioc_drive_link})")

    text = "\n".join(p for p in text_parts if p)

    payload = {
        "username": "SecurityBot",
        "icon_emoji": ":shield:",
        "text": text,
    }

    try:
        resp = requests.post(MATTERMOST_WEBHOOK, json=payload, timeout=10)
        resp.raise_for_status()
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        log.info("Mattermost alert sent for %s (CVE: %s)", intel.intel_id, cve_id)
        return now
    except requests.RequestException as e:
        log.error("Failed to send Mattermost alert: %s", e)
        return None
