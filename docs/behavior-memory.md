# Cross-chapter behavior memory

`SQLiteBehaviorMemory` is the durable storage seam for cross-chapter behavior history. It keeps the legacy `scenes`, `actors`, `plans`, and `history` tables readable while adding versioned identities, generation runs, accepted drafts, committed occurrences, and per-book memory revisions.

## Transaction guarantees

A formal commit writes the accepted draft, validated audit and extraction JSON, behavior occurrences, optional scene/world state, run status, and the next book revision in one `BEGIN IMMEDIATE` transaction. Every `extracted` occurrence must match one audited extraction behavior; human-confirmed additions use their explicit source instead. A stale audit raises `BEHAVIOR_MEMORY_REVISION_CONFLICT` when intervening history affects the same actor or current-scene ensemble; unrelated changes may commit safely. A reused formal position raises `BEHAVIOR_COMMIT_CONFLICT`. Replaying the same `run_id + accepted_revision + content_hash` returns the original commit result without adding rows.

Persisted run transitions are constrained to `prepared → drafted → audited_failed → rewritten → audited_passed → committed`, with a passing first audit allowing `drafted → audited_passed` and a failed audit allowing `audited_failed → abandoned`. Illegal transitions raise `RUN_STATE_CONFLICT` and survive process restarts without ambiguity.

The seven query windows are returned by `query_history`: `immediate`, `scene`, `chapter`, `recent_chapters`, `volume`, `book`, and `ensemble`. `explain_history_query_plans` exposes the SQLite plans used to verify the five required compound indexes.

## Legacy import

Legacy rows are never inferred into formal history. Supply a YAML mapping for every row to import:

```yaml
mappings:
  - legacy_history_rowid: 1
    position:
      book_id: book.hehuan
      volume_id: volume.01
      chapter_id: chapter.0001
      scene_id: scene.legacy
      paragraph_index: 3
      beat_index: 7
      global_beat_index: 7
    text_span: {start: 0, end: 6, text: "他攥紧手指。"}
    narrative_functions: [anger_leak]
    lexical_lemmas: [攥紧, 手指]
```

The `position.scene_id` and `position.beat_index` must match the old row. The supplied text span and all JSON fields are validated before the transaction starts.

```text
cpp-behavior-memory migrate-legacy mapping.yaml --db story.db
cpp-behavior-memory backup --db story.db --output story.backup.db
cpp-behavior-memory restore story.backup.db --db restored.db
```

Restore refuses to overwrite an existing destination unless `--overwrite` is explicit. The restored temporary database must pass SQLite's integrity check before it atomically replaces the destination.
