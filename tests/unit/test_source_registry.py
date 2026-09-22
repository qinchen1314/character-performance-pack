from pathlib import Path

import pytest

from character_performance.sources.registry import (
    BuildPolicy,
    LicenseGateError,
    SourceRegistry,
)


FIXTURE = Path(__file__).parents[1] / "fixtures" / "sources.yaml"


def test_commercial_build_accepts_only_approved_compatible_sources() -> None:
    registry = SourceRegistry.from_yaml(FIXTURE)

    decision = registry.validate_for_build(
        source_ids=["src.personachat.v1", "src.original.core.v1"],
        policy=BuildPolicy(commercial=True, redistribution=True),
    )

    assert decision.approved_source_ids == (
        "src.personachat.v1",
        "src.original.core.v1",
    )


@pytest.mark.parametrize(
    ("source_id", "reason"),
    [
        ("src.samm.v1", "review status is pending"),
        ("src.emobank.v1", "share-alike isolation"),
        ("src.unknown", "is not registered"),
    ],
)
def test_commercial_build_fails_closed_with_actionable_reason(
    source_id: str, reason: str
) -> None:
    registry = SourceRegistry.from_yaml(FIXTURE)

    with pytest.raises(LicenseGateError, match=reason):
        registry.validate_for_build(
            source_ids=[source_id],
            policy=BuildPolicy(commercial=True, redistribution=True),
        )


def test_reference_only_source_cannot_enter_a_compiled_pack() -> None:
    registry = SourceRegistry.from_yaml(FIXTURE)

    with pytest.raises(LicenseGateError, match="reference-only"):
        registry.validate_for_build(
            source_ids=["src.facs.v1"],
            policy=BuildPolicy(commercial=False, redistribution=False),
        )


def test_non_original_source_requires_license_evidence(tmp_path: Path) -> None:
    registry_path = tmp_path / "registry.yaml"
    registry_path.write_text(
        """
schema_version: 1.0.0
sources:
  - id: src.incomplete.v1
    name: Incomplete
    source_type: academic_dataset
    official_url: https://example.invalid/source
    version: pinned-v1
    retrieved_at: 2026-09-21
    concepts_used: [taxonomy]
    usage_mode: derived_metadata
    review_status: approved
    reviewer: project-owner
    reviewed_at: 2026-09-21
    content_hash: null
    license:
      identifier: unknown
      commercial_use: false
      redistribution: false
      attribution_required: true
      share_alike: false
      evidence_urls: []
""".strip(),
        encoding="utf-8",
    )
    registry = SourceRegistry.from_yaml(registry_path)

    with pytest.raises(LicenseGateError, match="license evidence"):
        registry.validate_for_build(
            source_ids=["src.incomplete.v1"],
            policy=BuildPolicy(commercial=False, redistribution=False),
        )
