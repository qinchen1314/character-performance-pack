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
