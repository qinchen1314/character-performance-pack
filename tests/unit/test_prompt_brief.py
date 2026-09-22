from __future__ import annotations

from character_performance.domain.behavior_models import (
    BehaviorFingerprint,
    BehaviorIdentity,
    BehaviorOccurrence,
    GenerationRequest,
    NarrativePosition,
    ReactionStrategyPlan,
    SyntaxFeatures,
    TextSpan,
    StyleContext,
)
from character_performance.domain.models import CharacterProfile, Context, Director, SceneState
from character_performance.memory import BehaviorMemorySnapshot
from character_performance.prompt_brief import (
    BriefBuildConfig,
    PromptBriefBuilder,
    PythonGenerationBriefAdapter,
    estimate_prompt_tokens,
)


def _position(beat: int = 20) -> NarrativePosition:
    return NarrativePosition(
        book_id="book.demo",
        volume_id="volume.1",
        chapter_id="chapter.4",
        scene_id="scene.4",
        paragraph_index=2,
        beat_index=3,
        global_beat_index=beat,
    )


def _identity() -> BehaviorIdentity:
    return BehaviorIdentity(
        character_id="char.a",
        version=1,
        default_strategies={"conflict": "conceal_then_counter"},
        preferred_channels={"hands": 0.9, "gaze": 0.8, "speech_rhythm": 0.7},
        avoided_channels={"physiology": 0.9},
        values=frozenset({"self_control"}),
        taboos=frozenset({"public_pleading"}),
        coping_strategies=frozenset({"observe"}),
        social_masks={"public": "controlled", "private": "terse", "intimate": "open"},
    )


def _request() -> GenerationRequest:
    return GenerationRequest(
        run_id="run.brief",
        position=_position(),
        character=CharacterProfile(id="char.a"),
        behavior_identity=_identity(),
        scene_state=SceneState(
            scene_id="scene.4",
            pose="standing",
            held_objects={"right_hand": "object.sword"},
        ),
        context=Context(
            activity="confrontation",
            privacy="public",
            facts=frozenset({"fact.left_shoulder_injured", "fact.back_against_wall"}),
        ),
        director=Director(max_signals=2, desired_visibility="subtle"),
        dialogue_or_plot_constraints=("keep_dialogue_meaning",),
        style_context=StyleContext(
            pov="third_limited", prose_style="concise", paragraph_function="confrontation"
        ),
    )


def _occurrence(index: int, *, group: str = "hand_tension", channel: str = "hands") -> BehaviorOccurrence:
    position = _position(index)
    position = position.model_copy(
        update={
            "chapter_id": "chapter.3",
            "scene_id": "scene.3",
            "global_beat_index": index,
            "beat_index": index,
        }
    )
    return BehaviorOccurrence(
        occurrence_id=f"occurrence.{index}",
        book_id="book.demo",
        position=position,
        actor_id="char.a",
        fingerprint=BehaviorFingerprint(
            unit_id="body.hand_clench" if group == "hand_tension" else None,
            semantic_groups=frozenset({group}),
            channel=channel,
            narrative_functions=frozenset({"anger_leak"}),
            actor_id="char.a",
            syntax_features=SyntaxFeatures(
                subject_opening="body_part",
                temporal_shape="brief_then_release",
                reset_pattern=True,
            ),
        ),
        source="extracted",
        text_span=TextSpan(start=0, end=2, text="他。"),
        confidence=0.9,
        generation_run_id=f"run.{index}",
        accepted_revision=1,
    )


def _snapshot(*items: BehaviorOccurrence) -> BehaviorMemorySnapshot:
    values = tuple(items)
    return BehaviorMemorySnapshot(
        memory_revision=47,
        immediate=values[-5:],
        scene=(),
        chapter=values,
        recent_chapters=values,
        volume=values,
        book=values,
        ensemble=values[-20:],
    )


def _strategy() -> ReactionStrategyPlan:
    return ReactionStrategyPlan(
        strategy_id="conceal_then_counter",
        intent="protect_status_without_escalation",
        surface_goal="maintain_courtesy",
        private_goal="retain_initiative",
        applicability_conditions=frozenset({"public_scene"}),
        contraindications=frozenset({"public_pleading"}),
        preferred_channels=("hands", "gaze", "speech_rhythm"),
        allowed_visibility="subtle",
        action_budget=2,
        omit_action_allowed=True,
        relationship_meaning="courtesy_without_submission",
        reasons=("public_scene",),
    )


def test_brief_compresses_context_blocks_recent_family_and_stays_in_budget(pack) -> None:
    history = _snapshot(_occurrence(1), _occurrence(2), _occurrence(3))
    builder = PromptBriefBuilder(
        pack,
        config=BriefBuildConfig(token_budget=96),
    )
    brief = builder.build(_request(), history, strategy=_strategy())

    assert brief.memory_revision == 47
    assert brief.maximum_visible_signals == 2
    assert brief.omit_action_allowed
    assert any(
        item.semantic_group == "hand_tension" and item.severity == "block"
        for item in brief.recently_overused
    )
    assert all("hand_tension" not in item.semantic_groups for item in brief.candidate_behaviors)
    assert len(brief.candidate_behaviors) <= 3
    assert estimate_prompt_tokens(brief.prompt_fragment) <= brief.token_budget
    assert brief.compressed_context["held_objects"] == {"right_hand": "object.sword"}
    assert "book" not in brief.compressed_context
    assert "score" not in brief.prompt_fragment.lower()


def test_python_adapter_and_builder_are_deterministic() -> None:
    request = _request()
    history = _snapshot()
    adapter = PythonGenerationBriefAdapter(PromptBriefBuilder())
    first = adapter.prepare(request, history)
    second = adapter.prepare(request, history)

    assert first == second
    assert first.run_id == request.run_id
    assert first.preferred_channels
    assert first.compressed_context["constraints"] == ["keep_dialogue_meaning"]


def test_tiny_token_budget_returns_valid_nonempty_prompt() -> None:
    brief = PromptBriefBuilder(config=BriefBuildConfig(token_budget=12)).build(
        _request(), _snapshot(), strategy=_strategy()
    )
    assert brief.prompt_fragment
    assert estimate_prompt_tokens(brief.prompt_fragment) <= 12


def test_world_candidates_require_complete_valid_world_state(pack) -> None:
    request = _request().model_copy(
        update={"director": Director(max_signals=2, allow_world=True)}
    )
    strategy = _strategy().model_copy(
        update={"preferred_channels": ("world",)}
    )

    brief = PromptBriefBuilder(pack).build(request, _snapshot(), strategy=strategy)

    assert not brief.candidate_behaviors
