from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import requests

from src.config import TWCERT_ACCOUNT, TWCERT_PASSWORD
from src.models import IntelItem
from src.parsers.ioc_xlsx import extract_iocs_from_info_file
from src.utils.errors import TwcertLoginError, send_ops_alert
from src.utils.logging import log

BASE_URL = "https://twisac.twcert.org.tw/tw-isac-web"
LOGIN_URL = f"{BASE_URL}/EnterpriseLoginController/login"
LIST_URL = f"{BASE_URL}/InfoListController/queryUserReceived"
DETAIL_URL = f"{BASE_URL}/InfoDetailController/queryInfoDetail"

PAGE_SIZE = 10

_TW = timezone(timedelta(hours=8))

_INFO_TYPE_MAP = {
    "101": "101-漏洞訊息",
    "102": "102-資安事件",
    "103": "103-資安預警",
    "104": "104-其他",
}

_IMPACT_MAP = {
    "IMPACT_LEVEL_1": "1",
    "IMPACT_LEVEL_2": "2",
    "IMPACT_LEVEL_3": "3",
}


def _parse_json(resp: requests.Response, context: str) -> dict:
    """Parse JSON from a response, logging rich diagnostics on failure."""
    try:
        return resp.json()
    except ValueError as e:  # JSONDecodeError subclasses ValueError
        body = (resp.text or "").strip()
        snippet = body[:500]
        log.error(
            "%s: non-JSON response (status=%s, content-type=%s, len=%d): %s",
            context,
            resp.status_code,
            resp.headers.get("Content-Type", ""),
            len(body),
            snippet or "<empty body>",
        )
        raise RuntimeError(
            f"{context}: server returned non-JSON "
            f"(status={resp.status_code}, "
            f"content-type={resp.headers.get('Content-Type', '')}): "
            f"{snippet or '<empty body>'}"
        ) from e


def _login(session: requests.Session) -> None:
    log.info("Logging in to TW-ISAC portal")
    resp = session.post(
        LOGIN_URL,
        json={
            "taxIdNumber": TWCERT_ACCOUNT,
            "password": TWCERT_PASSWORD,
            "remember": False,
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = _parse_json(resp, "TWCERT login")
    code = data.get("returnCode", "")
    if code != "00":
        msg = data.get("returnMesg", "Unknown error")
        send_ops_alert("TWCERT 登入失敗", f"returnCode={code}，訊息：{msg}")
        raise TwcertLoginError(f"Login failed: [{code}] {msg}")
    log.info("TW-ISAC login successful")


def _fetch_list_page(
    session: requests.Session,
    first: int,
    last: int,
    keyword: str = "",
) -> dict:
    resp = session.post(
        LIST_URL,
        json={
            "keyWord": keyword,
            "infoDetail": {
                "pageBean": {
                    "firstIndexInPage": first,
                    "lastIndexInPage": last,
                },
            },
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = _parse_json(resp, "TWCERT list query")
    if data.get("returnCode") != "00":
        raise RuntimeError(f"List query failed: {data.get('returnMesg')}")
    return data["restData"]


def _since_to_epoch_ms(since_date: str) -> float:
    """Convert YYYY-MM-DD (inclusive, Taiwan midnight) to epoch milliseconds."""
    dt = datetime.strptime(since_date, "%Y-%m-%d").replace(tzinfo=_TW)
    return dt.timestamp() * 1000


def _filter_and_check_cutoff(page_items: list[dict], cutoff_ms: float) -> tuple[list[dict], bool]:
    """Return (items_within_cutoff, should_stop).

    should_stop is True when any item on the page is older than the cutoff,
    meaning all subsequent pages will be even older.
    """
    kept: list[dict] = []
    stop = False
    for item in page_items:
        ts = item.get("publishDate") or 0
        if ts and ts < cutoff_ms:
            stop = True
        else:
            kept.append(item)
    return kept, stop


def _fetch_intel_list(
    session: requests.Session,
    since_date: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    cutoff_ms = _since_to_epoch_ms(since_date) if since_date else None

    rest = _fetch_list_page(session, 1, PAGE_SIZE)
    total = rest["infoDetail"]["pageBean"]["totalRecords"]
    page_items = list(rest.get("infoList") or [])
    log.info("Total intel items on server: %d (fetched first %d)", total, len(page_items))

    if cutoff_ms is not None:
        page_items, stop = _filter_and_check_cutoff(page_items, cutoff_ms)
        if stop:
            log.info("All remaining items are older than %s, stopping early", since_date)
            return page_items[:limit] if limit is not None else page_items

    items = page_items
    fetched = len(rest.get("infoList") or [])

    while fetched < total:
        if limit is not None and len(items) >= limit:
            break

        first = fetched + 1
        last = min(fetched + PAGE_SIZE, total)
        rest = _fetch_list_page(session, first, last)
        raw_page = rest.get("infoList") or []
        if not raw_page:
            break

        if cutoff_ms is not None:
            page_kept, stop = _filter_and_check_cutoff(raw_page, cutoff_ms)
            items.extend(page_kept)
            fetched += len(raw_page)
            log.info("Fetched %d / %d items (kept %d within cutoff)", fetched, total, len(items))
            if stop:
                log.info("All remaining items are older than %s, stopping early", since_date)
                break
        else:
            items.extend(raw_page)
            fetched += len(raw_page)
            log.info("Fetched %d / %d items", fetched, total)

    return items[:limit] if limit is not None else items


def _fetch_detail(session: requests.Session, info_id: str) -> dict:
    resp = session.post(
        DETAIL_URL,
        json={"infoDetail": {"infoId": info_id}},
        timeout=30,
    )
    resp.raise_for_status()
    data = _parse_json(resp, f"TWCERT detail query {info_id}")
    if data.get("returnCode") != "00":
        raise RuntimeError(f"Detail query failed for {info_id}: {data.get('returnMesg')}")
    return data["restData"]["infoDetail"]


def _epoch_ms_to_str(epoch_ms: int | float | None) -> str:
    if not epoch_ms:
        return ""
    dt = datetime.fromtimestamp(epoch_ms / 1000, tz=_TW)
    return dt.strftime("%Y-%m-%d %H:%M")


def _parse_reference_urls(ref_info: str | None) -> list[str]:
    if not ref_info:
        return []
    return re.findall(r"https?://\S+", ref_info)


def _resolve_info_type(code: str | None) -> str:
    if not code:
        return ""
    if "-" in code:
        return code
    return _INFO_TYPE_MAP.get(code, code)


def _resolve_impact_level(code: str | None) -> str:
    if not code:
        return ""
    return _IMPACT_MAP.get(code, code)


def _build_raw_content(detail: dict) -> str:
    sections = []
    if detail.get("infoContent"):
        sections.append(detail["infoContent"])
    if detail.get("impactPlatform"):
        sections.append(f"影響平台：{detail['impactPlatform']}")
    if detail.get("suggestResponse"):
        sections.append(f"建議措施：{detail['suggestResponse']}")
    if detail.get("refInfo"):
        sections.append(f"參考資訊：{detail['refInfo']}")
    impact = _resolve_impact_level(detail.get("impactLevelCd"))
    if impact:
        sections.append(f"TWCERT 影響等級：第 {impact} 級")
    return "\n\n".join(sections)


def _extract_cve_ids(text: str) -> list[str]:
    cves = re.findall(r"CVE-\d{4}-\d{4,}", text)
    return list(dict.fromkeys(cves))


def fetch_twcert(since_date: str | None = None, limit: int | None = None) -> list[IntelItem]:
    if since_date is None:
        since_date = datetime.now(_TW).strftime("%Y-%m-%d")

    session = requests.Session()
    session.headers.update(
        {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Referer": "https://twisac.twcert.org.tw/TW-ISAC/",
        }
    )

    try:
        _login(session)
        list_items = _fetch_intel_list(session, since_date, limit=limit)
    except TwcertLoginError:
        raise
    except Exception as e:
        send_ops_alert("TWCERT 爬蟲執行異常", f"擷取情資列表失敗：{e}")
        raise

    items: list[IntelItem] = []
    for entry in list_items:
        info_id = entry.get("infoId", "")
        try:
            detail = _fetch_detail(session, info_id)
        except Exception as e:
            log.warning("Failed to fetch detail for %s: %s", info_id, e)
            continue

        raw_content = _build_raw_content(detail)
        all_text = f"{detail.get('infoTitle', '')} {raw_content}"
        cve_ids = _extract_cve_ids(all_text)
        ref_urls = _parse_reference_urls(detail.get("refInfo"))

        info_type_code = detail.get("infoTypeCd") or entry.get("infoTypeCd", "")
        publish_ts = (
            entry.get("publishDate") or detail.get("lastPublishDate") or detail.get("shareDate")
        )

        info_file = detail.get("infoFile") or []
        ioc_ips, ioc_hashes, ioc_domains = extract_iocs_from_info_file(info_file)
        attachment_names = [f.get("fileName", "") for f in info_file if f.get("fileName")]

        item = IntelItem(
            intel_id=info_id,
            source="TWCERT",
            publish_date=_epoch_ms_to_str(publish_ts),
            title=detail.get("infoTitle", entry.get("infoTitle", "")),
            intel_type=_resolve_info_type(info_type_code),
            cve_ids=cve_ids,
            raw_content=raw_content,
            reference_urls=ref_urls,
            attachment_urls=attachment_names,
            ioc_ips=ioc_ips,
            ioc_hashes=ioc_hashes,
            ioc_domains=ioc_domains,
            impact_level=_resolve_impact_level(detail.get("impactLevelCd")),
        )
        items.append(item)

    log.info("Fetched %d intel items from TWCERT", len(items))
    return items
