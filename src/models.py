from __future__ import annotations

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
