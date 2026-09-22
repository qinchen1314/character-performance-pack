from character_performance.acceptance import (
    ExtractionBenchmarkCase,
    ExtractionTruth,
    benchmark_extractor,
    percentile,
)
from character_performance.domain.behavior_models import ExtractionRequest, NarrativePosition
from character_performance.domain.models import CharacterProfile
from character_performance.extraction import RuleBasedBehaviorExtractor


def test_extraction_benchmark_uses_independent_truth_and_exact_spans() -> None:
    text = "他把指甲掐进掌心。"
    request = ExtractionRequest(
        run_id="run.benchmark",
        text=text,
        known_characters=(CharacterProfile(id="char.a"),),
        position=NarrativePosition(
            book_id="book.a",
            chapter_id="chapter.1",
            scene_id="scene.1",
            paragraph_index=0,
            beat_index=0,
            global_beat_index=1,
        ),
    )
    result = benchmark_extractor(
        RuleBasedBehaviorExtractor(),
        (
            ExtractionBenchmarkCase(
                request=request,
                truths=(
                    ExtractionTruth(
                        actor_id="char.a",
                        semantic_group="hand_tension",
                        start=2,
                        end=8,
                    ),
                ),
            ),
        ),
    )

    assert result.true_positives == 1
    assert result.recall == 1
    assert result.precision == 1
    assert result.span_accuracy == 1


def test_percentile_is_nearest_rank_and_rejects_empty_samples() -> None:
    assert percentile((1, 2, 3, 100), 95) == 100
