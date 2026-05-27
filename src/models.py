from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime


@dataclass
class IntelItem:
    intel_id: str
    source: str  # "TWCERT" or "CISA_KEV"
    publish_date: str
    title: str
    intel_type: str  # e.g. "101-漏洞訊息", "IoC"
    cve_ids: list[str] = field(default_factory=list)
    raw_content: str = ""
    reference_urls: list[str] = field(default_factory=list)
    attachment_urls: list[str] = field(default_factory=list)
    ioc_ips: list[str] = field(default_factory=list)
    ioc_hashes: list[str] = field(default_factory=list)
    ioc_domains: list[str] = field(default_factory=list)
    impact_level: str = ""   # "1" / "2" / ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> IntelItem:
        return cls(**data)


@dataclass
class AnalysisResult:
    risk_level: str  # Critical / High / Medium / Low / 無
    summary: str
    recommendation: str
    company_relevance: str  # H / M / L / 無
    affected_assets: list[str] = field(default_factory=list)
    responsible_unit: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AnalysisResult":
        return cls(**data)


@dataclass
class SheetRow:
    record_date: str  # A
    intel_id: str  # B (with CVE suffix for multi-CVE)
    source: str  # C
    publish_date: str  # D
    title: str  # E
    intel_type: str  # F
    cve_id: str  # G (single CVE per row)
    recommendation: str  # H
    risk_level: str  # I
    summary: str  # J
    company_relevance: str  # K
    affected_assets: str  # L
    responsible_unit: str  # M
    status: str = "待處理"  # N
    tracking_link: str = ""  # O
    notes: str = ""  # P
    completion_date: str = ""  # Q
    handler: str = ""  # R
    notification_time: str = ""  # S
    impact_level: str = ""  # T
    reference_urls: str = ""  # U

    def to_row_list(self) -> list[str]:
        return [
            self.record_date,
            self.intel_id,
            self.source,
            self.publish_date,
            self.title,
            self.intel_type,
            self.cve_id,
            self.recommendation,
            self.risk_level,
            self.summary,
            self.company_relevance,
            self.affected_assets,
            self.responsible_unit,
            self.status,
            self.tracking_link,
            self.notes,
            self.completion_date,
            self.handler,
            self.notification_time,
            self.impact_level,
            self.reference_urls,
        ]

    @staticmethod
    def from_intel_and_analysis(
        intel: IntelItem,
        analysis: AnalysisResult,
        cve_id: str,
        intel_id_suffix: str = "",
        ioc_drive_link: str = "",
    ) -> SheetRow:
        now = datetime.now().strftime("%Y-%m-%d")
        row_intel_id = intel.intel_id
        if intel_id_suffix:
            row_intel_id = f"{intel.intel_id}-{intel_id_suffix}"

        recommendation = analysis.recommendation
        if ioc_drive_link:
            recommendation += f"\n\nIoC 清單下載：{ioc_drive_link}"

        return SheetRow(
            record_date=now,
            intel_id=row_intel_id,
            source=intel.source,
            publish_date=intel.publish_date,
            title=intel.title,
            intel_type=intel.intel_type,
            cve_id=cve_id,
            recommendation=recommendation,
            risk_level=analysis.risk_level,
            summary=analysis.summary,
            company_relevance=analysis.company_relevance,
            affected_assets=", ".join(analysis.affected_assets),
            responsible_unit=analysis.responsible_unit,
            reference_urls="\n".join(intel.reference_urls),
            impact_level=intel.impact_level,
        )
