from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone

from src.analyzer.gemini import analyze_intel
from src.config import USE_FIXTURE_DATA
from src.fetchers.cisa_kev import fetch_cisa_kev
from src.fetchers.storage import (
    list_saved_files,
    load_analysis,
    load_items,
    save_analysis,
    save_items,
)
from src.fetchers.twcert import fetch_twcert
from src.models import AnalysisResult, IntelItem
from src.notifiers.email import send_internal_announcement, send_risk_digest
from src.parsers.ioc_xlsx import write_ioc_txt
from src.sinks.git_archive import commit_files, ioc_file_url
from src.sinks.sheets import (
    append_monthly,
    append_pool_raw,
    backfill_pool_analysis,
    get_month_rows,
    get_rows_for_publishing,
    load_assets_context,
    mark_published,
    month_tab_url,
    relevance_label,
    select_relevant,
)
from src.utils.errors import GeminiQuotaExhausted, TwcertLoginError
from src.utils.logging import log

_TW = timezone(timedelta(hours=8))


def _archive_dir(source: str, date_str: str | None) -> str:
    if date_str and len(date_str) >= 7 and date_str[4] == "-":
        month = date_str[:7]
    else:
        month = datetime.now(_TW).strftime("%Y-%m")
    return f"{source}/{month}"


def stage_fetch(
    source: str,
    since_date: str | None = None,
    save: bool = False,
    limit: int | None = None,
) -> list[IntelItem]:
    if source == "twcert":
        items = fetch_twcert(since_date, limit=limit)
    elif source == "cisa_kev":
        items = fetch_cisa_kev(since_date)
        if limit is not None:
            items = items[:limit]
            log.info("Limiting to %d items", len(items))
    else:
        raise ValueError(f"Unknown source: {source}")
    if save:
        path = save_items(items, source, tag=since_date)
        commit_files(
            [path],
            f"data({source}): fetch {since_date or 'latest'}, {len(items)} items",
            archive_dir=_archive_dir(source, since_date),
        )
    return items


def stage_append_pool_raw(items: list[IntelItem], dry_run: bool = False) -> list[IntelItem]:
    """Append raw rows to the POOL tab; return the newly-appended (new) items."""
    if dry_run:
        log.info("[DRY RUN] Pool append skipped; treating all %d items as new", len(items))
        return items
    new_items = append_pool_raw(items)
    log.info(
        "Pool: %d new items appended (skipped %d duplicates)",
        len(new_items),
        len(items) - len(new_items),
    )
    return new_items


def stage_analyze(
    items: list[IntelItem],
    source: str,
    save: bool = False,
    tag: str | None = None,
    limit: int | None = None,
) -> list[tuple[IntelItem, AnalysisResult]]:
    if limit is not None:
        items = items[:limit]
        log.info("Limiting analysis to %d items", len(items))
    if not items:
        log.info("No items to analyze")
        return []

    log.info("Analyzing %d items", len(items))

    assets_ctx = load_assets_context()

    pairs: list[tuple[IntelItem, AnalysisResult]] = []
    for item in items:
        try:
            analysis = analyze_intel(item, assets_ctx)
        except GeminiQuotaExhausted:
            log.error(
                "Gemini quota exhausted, stopping. Remaining items will be processed next run."
            )
            break
        log.info(
            "Analyzed %s: risk=%s, relevance=%s",
            item.intel_id,
            analysis.risk_level,
            analysis.company_relevance,
        )
        pairs.append((item, analysis))

    if save and pairs:
        path = save_analysis(pairs, source, tag=tag)
        commit_files(
            [path],
            f"data({source}): analysis {tag or 'latest'}, {len(pairs)} pairs",
            archive_dir=_archive_dir(source, tag),
        )
    return pairs


def _archive_iocs(pairs: list[tuple[IntelItem, AnalysisResult]]) -> dict[str, str]:
    """Write each item's IoC list to a .txt, commit it to the archive branch, and
    return {intel_id: raw-URL} so the URL can be surfaced in the 建議措施 column.

    No-ops (empty dict) when GIT_ARCHIVE_BRANCH is unset (commit_files/ioc_file_url
    short-circuit) or an item has no IoCs.
    """
    urls: dict[str, str] = {}
    for intel, _ in pairs:
        ioc_path = write_ioc_txt(intel.intel_id, intel.ioc_ips, intel.ioc_hashes, intel.ioc_domains)
        if not ioc_path:
            continue
        src_lower = intel.source.lower()
        month = (intel.publish_date or "")[:7] or datetime.now(_TW).strftime("%Y-%m")
        adir = f"{src_lower}/{month}"
        commit_files([ioc_path], f"data({src_lower}): IoC for {intel.intel_id}", archive_dir=adir)
        url = ioc_file_url(ioc_path.name, adir)
        if url:
            urls[intel.intel_id] = url
    return urls


def stage_write_sheet(
    pairs: list[tuple[IntelItem, AnalysisResult]],
    dry_run: bool = False,
) -> int:
    """Backfill the POOL analysis columns and append relevant items to monthly tabs."""
    if not pairs:
        log.info("No analyzed pairs to write")
        return 0

    if dry_run:
        log.info(
            "[DRY RUN] Would backfill %d pool rows and append relevant items to monthly tabs",
            len(pairs),
        )
        for intel, analysis in pairs:
            log.info(
                "  %s | %s | %s | %s",
                intel.intel_id,
                analysis.risk_level,
                relevance_label(analysis.company_relevance),
                intel.title[:50],
            )
        return len(pairs)

    ioc_urls = _archive_iocs(pairs)
    n_backfill = backfill_pool_analysis(pairs, ioc_urls)
    n_monthly = append_monthly(pairs, ioc_urls)
    log.info("Pool backfilled: %d rows; Monthly appended: %d rows", n_backfill, n_monthly)
    return n_backfill


def stage_notify_risk(month: str | None = None, dry_run: bool = False) -> int:
    month = month or datetime.now(_TW).strftime("%Y/%m")
    records = get_month_rows(month)
    relevant = select_relevant(records)
    if not relevant:
        log.info("No company-relevant intel for %s, skipping risk digest", month)
        return 0
    sheet_url = month_tab_url(month)
    ok = send_risk_digest(month, relevant, sheet_url, dry_run=dry_run)
    log.info("Risk digest for %s: %d items, sent=%s", month, len(relevant), ok)
    return len(relevant) if ok else 0


def stage_publish_internal(dry_run: bool = False) -> int:
    targets = get_rows_for_publishing()
    if not targets:
        log.info("No approved intel to publish")
        return 0
    records = [t["record"] for t in targets]
    ok = send_internal_announcement(records, dry_run=dry_run)
    if ok and not dry_run and not USE_FIXTURE_DATA:
        ts = datetime.now(_TW).strftime("%Y-%m-%d %H:%M:%S")
        mark_published(targets, ts)
    log.info("Internal publish: %d approved items, sent=%s", len(targets), ok)
    return len(targets) if ok else 0


def run(
    source: str,
    dry_run: bool = False,
    since_date: str | None = None,
    save_data: bool = True,
    load_data: str | None = None,
    fetch_only: bool = False,
    analyze_only: bool = False,
    load_analysis_path: str | None = None,
    limit: int | None = None,
) -> None:
    # --- Stage 3+ (from analysis JSON) ---
    if load_analysis_path:
        log.info("=== %s Stage 3: Write Sheet ===", source.upper())
        pairs = load_analysis(load_analysis_path)
        stage_write_sheet(pairs, dry_run=dry_run)
        log.info("=== %s 完成 ===", source.upper())
        return

    # --- Stage 1: Fetch ---
    log.info("=== %s 情資%s開始 ===", source.upper(), "擷取" if fetch_only else "分析")
    if load_data:
        items = load_items(load_data)
        if limit is not None:
            items = items[:limit]
            log.info("Limiting to %d items", len(items))
    else:
        items = stage_fetch(
            source, since_date=since_date, save=save_data or fetch_only, limit=limit
        )

    if not items:
        log.info("No items fetched")
        return

    if fetch_only:
        log.info("Fetch-only mode: %d items saved, skipping analysis", len(items))
        return

    # --- Stage 1.5: Append raw rows to POOL, dedup by 情資編號 → new items ---
    new_items = stage_append_pool_raw(items, dry_run=dry_run)
    if not new_items:
        log.info("No new intel items (all already in pool)")
        return

    # --- Stage 2: Analyze ---
    pairs = stage_analyze(new_items, source, save=save_data, tag=since_date, limit=limit)
    if not pairs:
        return

    if analyze_only:
        log.info("Analyze-only mode: %d pairs saved, skipping Sheet write", len(pairs))
        return

    # --- Stage 3: Backfill POOL analysis + append relevant items to monthly tabs ---
    stage_write_sheet(pairs, dry_run=dry_run)
    log.info("=== %s 情資分析完成 ===", source.upper())


def cmd_list_data(source: str | None) -> None:
    files = list_saved_files(source)
    if not files:
        print("No saved data files found.")
        return
    print(f"Saved data files ({len(files)}):\n")
    for f in files:
        print(f"  {f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="資安情資 AI 自動化分析系統")
    parser.add_argument(
        "--source",
        help="情資來源：twcert 或 cisa_kev（--list-data 時可用任意前綴，如 analysis_twcert）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="模擬執行，不寫入 Sheet 也不上傳 Drive",
    )
    parser.add_argument(
        "--since",
        type=str,
        default=None,
        metavar="DATE",
        help="僅擷取指定日期（含）之後的情資 (YYYY-MM-DD)，預設為今天",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="限制 Stage 1/2 處理的最大項目數量（測試用）",
    )

    stage_group = parser.add_mutually_exclusive_group()
    stage_group.add_argument(
        "--fetch-only",
        action="store_true",
        help="僅擷取情資並儲存至本機，不執行 AI 分析",
    )
    stage_group.add_argument(
        "--analyze-only",
        action="store_true",
        help="執行到 Gemini 分析後停止，將結果儲存為 analysis_*.json",
    )
    parser.add_argument(
        "--no-save-data",
        action="store_false",
        dest="save_data",
        help="不儲存中間檔案至本機 data/ 目錄（預設會儲存）",
    )
    parser.add_argument(
        "--load-data",
        type=str,
        default=None,
        metavar="FILE",
        help="從本機 fetch JSON 載入情資，跳過遠端擷取（從 Stage 2 開始）",
    )
    parser.add_argument(
        "--load-analysis",
        type=str,
        default=None,
        metavar="FILE",
        help="從本機 analysis JSON 載入分析結果，跳過 Stage 1–2（從 Stage 3 開始）",
    )
    parser.add_argument(
        "--list-data",
        action="store_true",
        help="列出已儲存的本機資料檔案",
    )
    parser.add_argument(
        "--notify-risk",
        action="store_true",
        help="寄送當月風險小組月會彙整信（Stage 4a）",
    )
    parser.add_argument(
        "--publish-internal",
        action="store_true",
        help="掃描 Sheet 已核可情資並發佈給 RD 主管（Stage 4b）",
    )
    parser.add_argument(
        "--month",
        type=str,
        default=None,
        metavar="YYYY/MM",
        help="--notify-risk 的目標月份（斜線格式），預設當月",
    )

    args = parser.parse_args()

    if args.list_data:
        cmd_list_data(args.source)
        return

    if not (args.notify_risk or args.publish_internal):
        if not args.source:
            parser.error("--source is required")
        if args.source not in ("twcert", "cisa_kev"):
            parser.error(f"--source must be 'twcert' or 'cisa_kev' (got '{args.source}')")

    try:
        if args.publish_internal:
            stage_publish_internal(dry_run=args.dry_run)
        elif args.notify_risk:
            stage_notify_risk(month=args.month, dry_run=args.dry_run)
        else:
            run(
                source=args.source,
                dry_run=args.dry_run,
                since_date=args.since,
                save_data=args.save_data,
                load_data=args.load_data,
                fetch_only=args.fetch_only,
                analyze_only=args.analyze_only,
                load_analysis_path=args.load_analysis,
                limit=args.limit,
            )
    except TwcertLoginError:
        log.error("TWCERT login failed, ops alert already sent")
        sys.exit(1)
    except GeminiQuotaExhausted:
        log.error("Gemini quota exhausted, partial results may have been written")
        sys.exit(1)
    except Exception as e:
        log.error("Unexpected error: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
