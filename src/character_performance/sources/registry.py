from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field


class LicenseGateError(ValueError):
    """A source cannot be used under the requested build policy."""


class LicenseInfo(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    identifier: str
    commercial_use: bool | None
    redistribution: bool | None
    attribution_required: bool
    share_alike: bool
    evidence_urls: tuple[str, ...] = ()


class SourceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^src\.[a-z0-9_.-]+$")
    name: str
    source_type: Literal[
        "academic_dataset", "behavioral_model", "specification", "original"
    ]
    version: str
    usage_mode: Literal[
        "reference_only",
        "derived_metadata",
        "transform_allowed",
        "redistribution_allowed",
        "original",
        "blocked",
    ]
    review_status: Literal["approved", "pending", "rejected"]
    isolation: Literal["none", "share_alike"] = "none"
    license: LicenseInfo


class SourceRegistryDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str
    sources: tuple[SourceRecord, ...]


@dataclass(frozen=True)
class BuildPolicy:
    commercial: bool
    redistribution: bool
    allow_share_alike: bool = False


@dataclass(frozen=True)
class BuildDecision:
    approved_source_ids: tuple[str, ...]


class SourceRegistry:
    def __init__(self, document: SourceRegistryDocument) -> None:
        self.schema_version = document.schema_version
        self._records = {record.id: record for record in document.sources}
        if len(self._records) != len(document.sources):
            raise ValueError("source registry contains duplicate ids")

    @classmethod
    def from_yaml(cls, path: Path) -> "SourceRegistry":
        with path.open("r", encoding="utf-8") as stream:
            raw = yaml.safe_load(stream)
        return cls(SourceRegistryDocument.model_validate(raw))

    def get(self, source_id: str) -> SourceRecord:
        try:
            return self._records[source_id]
        except KeyError as error:
            raise LicenseGateError(f"source {source_id!r} is not registered") from error

    def validate_for_build(
        self, source_ids: list[str] | tuple[str, ...], policy: BuildPolicy
    ) -> BuildDecision:
        approved: list[str] = []
        for source_id in source_ids:
            record = self.get(source_id)
            self._validate_record(record, policy)
            if source_id not in approved:
                approved.append(source_id)
        return BuildDecision(tuple(approved))

    @staticmethod
    def _validate_record(record: SourceRecord, policy: BuildPolicy) -> None:
        if record.review_status != "approved":
            raise LicenseGateError(
                f"source review status is {record.review_status}: {record.id}"
            )
        if record.usage_mode == "blocked":
            raise LicenseGateError(f"source usage is blocked: {record.id}")
        if record.isolation == "share_alike" and not policy.allow_share_alike:
            raise LicenseGateError(
                f"source requires share-alike isolation: {record.id}"
            )
        if policy.commercial and record.license.commercial_use is not True:
            raise LicenseGateError(f"commercial use is not approved: {record.id}")
        if policy.redistribution and record.license.redistribution is not True:
            raise LicenseGateError(f"redistribution is not approved: {record.id}")

