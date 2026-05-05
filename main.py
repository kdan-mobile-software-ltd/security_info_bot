from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.analyzer.gemini import analyze_intel
from src.fetchers.cisa_kev import fetch_cisa_kev
from src.fetchers.storage import list_saved_files, load_items, save_items
from src.fetchers.twcert import fetch_twcert
from src.models import IntelItem, SheetRow
from src.parsers.ioc_xlsx import download_and_parse_ioc_xlsx, write_ioc_txt
from src.sinks.drive import upload_ioc_file
from src.sinks.mattermost import send_intel_alert
from src.sinks.sheets import (
    append_rows,
    get_existing_intel_ids,
    load_assets_context,
    load_rules_context,
    load_units_context,
    update_notification_time,
)
from src.utils.errors import GeminiQuotaExhausted, TwcertLoginError
from src.utils.logging import log


def process_intel_items(
    items: list[IntelItem],
    existing_ids: set[str],
    assets_ctx: str,
    units_ctx: str,
    rules_ctx: str,
    dry_run: bool = False,
) -> None:
    new_items = [item for item in items if item.intel_id not in existing_ids]
    if not new_items:
        log.info("No new intel items to process (all %d already exist)", len(items))
        return

    log.info("Processing %d new items (skipped %d duplicates)", len(new_items), len(items) - len(new_items))

    all_rows: list[SheetRow] = []

    for item in new_items:
        ioc_drive_link = ""
        ioc_path: "Path | None" = None
        for att_url in item.attachment_urls:
            if att_url.lower().endswith((".xlsx", ".xls")):
                ioc_path = download_and_parse_ioc_xlsx(att_url, item.intel_id)
                break
        if ioc_path is None and item.ioc_ips:
            ioc_path = write_ioc_txt(item.intel_id, item.ioc_ips)
        if ioc_path and not dry_run:
            ioc_drive_link = upload_ioc_file(ioc_path)

        try:
            analysis = analyze_intel(item, assets_ctx, units_ctx, rules_ctx)
        except GeminiQuotaExhausted:
            log.error("Gemini quota exhausted, stopping. Remaining items will be processed next run.")
            break

        log.info(
            "Analyzed %s: risk=%s, relevance=%s",
            item.intel_id, analysis.risk_level, analysis.company_relevance,
        )

        cve_list = item.cve_ids if item.cve_ids else [""]
        for idx, cve_id in enumerate(cve_list):
            suffix = str(idx + 1) if len(cve_list) > 1 else ""
            row = SheetRow.from_intel_and_analysis(
                intel=item,
                analysis=analysis,
                cve_id=cve_id,
                intel_id_suffix=suffix,
                ioc_drive_link=ioc_drive_link,
            )
            all_rows.append(row)

            if not dry_run:
                notification_time = send_intel_alert(
                    intel=item,
                    analysis=analysis,
                    cve_id=cve_id,
                    ioc_drive_link=ioc_drive_link,
                )
                if notification_time:
                    row.notification_time = notification_time

    if dry_run:
        log.info("[DRY RUN] Would write %d rows to Sheet", len(all_rows))
        for row in all_rows:
            log.info(
                "  %s | %s | %s | %s",
                row.intel_id, row.cve_id, row.risk_level, row.title[:50],
            )
        return

    count = append_rows(all_rows)
    log.info("Done. Wrote %d rows total.", count)

    for row in all_rows:
        if row.notification_time:
            row_id = row.intel_id
            update_notification_time(row_id, row.notification_time)


def _fetch_items(
    source: str,
    target_date: str | None = None,
    since_date: str | None = None,
) -> list[IntelItem]:
    if source == "twcert":
        return fetch_twcert(since_date)
    elif source == "cisa_kev":
        return fetch_cisa_kev(target_date)
    raise ValueError(f"Unknown source: {source}")


def run(
    source: str,
    dry_run: bool = False,
    target_date: str | None = None,
    since_date: str | None = None,
    save_data: bool = False,
    load_data: str | None = None,
    fetch_only: bool = False,
) -> None:
    log.info("=== %s 情資%s開始 ===", source.upper(), "擷取" if fetch_only else "分析")

    if load_data:
        items = load_items(load_data)
    else:
        items = _fetch_items(source, target_date, since_date)

    if not items:
        log.info("No items fetched")
        return

    if save_data or fetch_only:
        save_items(items, source, tag=target_date)

    if fetch_only:
        log.info("Fetch-only mode: saved %d items, skipping analysis", len(items))
        return

    existing_ids = set() if dry_run else get_existing_intel_ids()
    assets_ctx = load_assets_context()
    units_ctx = load_units_context()
    rules_ctx = load_rules_context()

    process_intel_items(items, existing_ids, assets_ctx, units_ctx, rules_ctx, dry_run)
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
        choices=["twcert", "cisa_kev"],
        help="情資來源：twcert 或 cisa_kev",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="模擬執行，不寫入 Sheet 也不發送通報",
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="指定 CISA KEV 目標日期 (YYYY-MM-DD)，預設為今天",
    )
    parser.add_argument(
        "--since",
        type=str,
        default=None,
        metavar="DATE",
        help="僅擷取 TWCERT 指定日期（含）之後的情資 (YYYY-MM-DD)，預設不限制",
    )
    parser.add_argument(
        "--fetch-only",
        action="store_true",
        help="僅擷取情資並儲存至本機，不執行 AI 分析與通報",
    )
    parser.add_argument(
        "--save-data",
        action="store_true",
        help="將擷取的情資儲存至本機 data/ 目錄（JSON 格式）",
    )
    parser.add_argument(
        "--load-data",
        type=str,
        default=None,
        metavar="FILE",
        help="從本機 JSON 檔案載入情資，跳過遠端擷取",
    )
    parser.add_argument(
        "--list-data",
        action="store_true",
        help="列出已儲存的本機資料檔案",
    )

    args = parser.parse_args()

    if args.list_data:
        cmd_list_data(args.source)
        return

    if not args.source and not args.load_data:
        parser.error("--source is required unless using --load-data")

    if args.load_data and not args.source:
        parser.error("--source is required with --load-data to select the processing pipeline")

    try:
        run(
            source=args.source,
            dry_run=args.dry_run,
            target_date=args.date,
            since_date=args.since,
            save_data=args.save_data,
            load_data=args.load_data,
            fetch_only=args.fetch_only,
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
