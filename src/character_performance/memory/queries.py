"""Parameterized occurrence queries shared by SQLite memory windows."""

OCCURRENCE_COLUMNS = """
    occurrence_id, run_id, book_id, volume_id, chapter_id, scene_id,
    global_beat_index, paragraph_index, beat_index, timeline_ms, actor_id,
    target_ids, unit_id, semantic_groups, channel, narrative_functions,
    strategy_id, visibility, amplitude_band, syntax_features, lexical_lemmas,
    source, confidence, text_start, text_end, text, accepted_revision
"""

__all__ = ["OCCURRENCE_COLUMNS"]
