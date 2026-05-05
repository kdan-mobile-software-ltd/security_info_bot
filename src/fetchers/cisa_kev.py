from __future__ import annotations

from datetime import datetime, timezone

import requests

from src.models import IntelItem
from src.utils.logging import log

CISA_KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"


def fetch_cisa_kev(target_date: str | None = None) -> list[IntelItem]:
    if target_date is None:
        target_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    log.info("Fetching CISA KEV feed, filtering for date: %s", target_date)

    resp = requests.get(CISA_KEV_URL, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    vulnerabilities = data.get("vulnerabilities", [])
    items: list[IntelItem] = []

    for vuln in vulnerabilities:
        date_added = vuln.get("dateAdded", "")
        if date_added != target_date:
            continue

        cve_id = vuln.get("cveID", "")
        vendor = vuln.get("vendorProject", "")
        product = vuln.get("product", "")
        name = vuln.get("vulnerabilityName", "")
        description = vuln.get("shortDescription", "")
        action = vuln.get("requiredAction", "")
        due_date = vuln.get("dueDate", "")
        notes_url = vuln.get("notes", "")
        known_ransomware = vuln.get("knownRansomwareCampaignUse", "Unknown")

        title = f"[CISA KEV] {vendor} {product} - {name}"

        raw_content = (
            f"CVE: {cve_id}\n"
            f"廠商: {vendor}\n"
            f"產品: {product}\n"
            f"漏洞名稱: {name}\n"
            f"說明: {description}\n"
            f"CISA 要求措施: {action}\n"
            f"修補截止日: {due_date}\n"
            f"已知勒索軟體利用: {known_ransomware}\n"
        )

        refs = []
        if notes_url:
            refs.append(notes_url)
        refs.append(f"https://nvd.nist.gov/vuln/detail/{cve_id}")

        item = IntelItem(
            intel_id=cve_id,
            source="CISA_KEV",
            publish_date=date_added,
            title=title,
            intel_type="101-漏洞訊息",
            cve_ids=[cve_id],
            raw_content=raw_content,
            reference_urls=refs,
        )
        items.append(item)

    log.info("Found %d new CISA KEV entries for %s", len(items), target_date)
    return items
