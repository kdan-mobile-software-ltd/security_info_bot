from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class IntelItem(BaseModel):
    intel_id: str
    source: str
    publish_date: str
    title: str
    intel_type: str
    cve_ids: list[str] = Field(default_factory=list)
    raw_content: str = ""
    reference_urls: list[str] = Field(default_factory=list)
    attachment_urls: list[str] = Field(default_factory=list)
    ioc_ips: list[str] = Field(default_factory=list)
    ioc_hashes: list[str] = Field(default_factory=list)
    ioc_domains: list[str] = Field(default_factory=list)
    impact_level: str = ""

    def to_dict(self) -> dict:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict) -> IntelItem:
        return cls.model_validate(data)


class AnalysisResult(BaseModel):
    risk_level: Literal["Critical", "High", "Medium", "Low", "無"]
    summary: str
    recommendation: str
    company_relevance: Literal["H", "M", "L", "無"]
    affected_assets: list[str] = Field(default_factory=list)
    responsible_unit: str = ""

    def to_dict(self) -> dict:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict) -> AnalysisResult:
        return cls.model_validate(data)


class SheetRow(BaseModel):
    record_date: str  # A
    intel_id: str  # B
    source: str  # C
    publish_date: str  # D
    title: str  # E
    intel_type: str  # F
    cve_id: str  # G (newline-separated when multiple CVEs)
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
        ioc_url: str = "",
    ) -> SheetRow:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        recommendation = analysis.recommendation
        if ioc_url:
            recommendation += f"\n\nIoC 清單：{ioc_url}"

        status = "不適用" if analysis.company_relevance == "無" else "待處理"

        return SheetRow(
            record_date=now,
            intel_id=intel.intel_id,
            source=intel.source,
            publish_date=intel.publish_date,
            title=intel.title,
            intel_type=intel.intel_type,
            cve_id="\n".join(intel.cve_ids),
            recommendation=recommendation,
            risk_level=analysis.risk_level,
            summary=analysis.summary,
            company_relevance=analysis.company_relevance,
            affected_assets=", ".join(analysis.affected_assets),
            responsible_unit=analysis.responsible_unit,
            status=status,
            reference_urls="\n".join(intel.reference_urls),
            impact_level=intel.impact_level,
        )
