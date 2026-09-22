from __future__ import annotations

import pytest

from character_performance.domain.behavior_models import ArcState, BehaviorIdentity, RelationshipStrategyOverride
from character_performance.domain.models import CharacterProfile, Event, RelationshipState, SceneState
from character_performance.identity import (
    BehaviorIdentityMissingError,
    BehaviorIdentityRegistry,
    ReactionStrategyPlanner,
    StrategyContext,
    sample_identity_shells,
)


def _identity() -> BehaviorIdentity:
    return BehaviorIdentity(
        character_id="char.controlled",
        version=2,
        default_strategies={"conflict": "conceal_then_counter", "threat": "freeze"},
        preferred_channels={"gaze": 0.9, "speech_rhythm": 0.8},
        avoided_channels={"hands": 0.8},
        values=frozenset({"self_control"}),
        taboos=frozenset({"confront"}),
        coping_strategies=frozenset({"observe"}),
        social_masks={"public": "public", "private": "private", "intimate": "intimate"},
        arc_state=ArcState(id="arc.recovery", allowed_exceptions=frozenset({"confront"})),
        relationship_overrides={
            "char.master": RelationshipStrategyOverride(
                preferred_strategies=("formal_compliance",),
                forbidden_strategies=frozenset({"confront"}),
            )
        },
    )


def _context(target: str = "char.enemy") -> StrategyContext:
    character = CharacterProfile(id="char.controlled")
    return StrategyContext(
        character=character,
        relation=RelationshipState(subject_id=character.id, target_id=target, hostility=0.8),
        event=Event(id="event.public_insult", publicness=0.9, threat={"social": 0.8}),
        scene=SceneState(scene_id="scene.1"),
        publicness=0.9,
        intent="conflict",
        target_id=target,
        seed=19,
    )


def test_planner_applies_arc_exception_and_relationship_forbidden_strategy() -> None:
    planner = ReactionStrategyPlanner()
    identity = _identity()
    ranked = planner.rank(_context(), identity=identity)
    assert next(item for item in ranked if item.strategy_id == "confront").accepted
    assert planner.plan(_context(), identity=identity).strategy_id == "conceal_then_counter"

    master = planner.plan(_context("char.master"), identity=identity)
    assert master.strategy_id != "confront"


def test_identity_registry_requires_missing_identity_and_keeps_latest_version() -> None:
    registry = BehaviorIdentityRegistry()
    with pytest.raises(BehaviorIdentityMissingError):
        registry.require("book.demo", "char.missing")
    registry.register("book.demo", _identity(), persist=False)
    assert registry.load("book.demo", "char.controlled").version == 2


def test_public_pleading_taboo_does_not_block_formal_authority_compliance() -> None:
    identity = _identity().model_copy(
        update={
            "taboos": frozenset({"public_pleading"}),
            "default_strategies": {"authority": "formal_compliance", "conflict": "conceal_then_counter"},
        }
    )
    context = _context("char.master")
    context = StrategyContext(
        character=context.character,
        relation=context.relation.model_copy(update={"dominance": -0.8, "hostility": 0.0}),
        event=context.event,
        scene=context.scene,
        publicness=0.9,
        intent="authority",
        target_id="char.master",
        seed=19,
    )

    assert ReactionStrategyPlanner().plan(context, identity=identity).strategy_id == "formal_compliance"


def test_ten_regression_shells_are_distinct_and_have_complete_identity_fields() -> None:
    shells = sample_identity_shells()
    assert len(shells) == 10
    assert len({item.default_strategies["conflict"] for item in shells}) >= 8
    assert all(item.preferred_channels and item.values and item.social_masks for item in shells)
