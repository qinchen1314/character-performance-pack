from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from character_performance.domain.models import EmotionState, OntologyEmotion


class UnknownEmotionError(KeyError):
    pass


class EmotionOntologyDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str
    emotions: tuple[OntologyEmotion, ...]


class EmotionOntology:
    def __init__(self, document: EmotionOntologyDocument) -> None:
        self.schema_version = document.schema_version
        self._emotions = {emotion.id: emotion for emotion in document.emotions}
        if len(self._emotions) != len(document.emotions):
            raise ValueError("emotion ontology contains duplicate ids")

        self._aliases: dict[str, str] = {}
        for emotion in document.emotions:
            for token in {emotion.id, emotion.label_zh, *emotion.aliases}:
                normalized = self._normalize(token)
                owner = self._aliases.get(normalized)
                if owner is not None and owner != emotion.id:
                    raise ValueError(
                        f"emotion alias {token!r} is shared by {owner!r} and {emotion.id!r}"
                    )
                self._aliases[normalized] = emotion.id

    @classmethod
    def from_yaml(cls, path: Path) -> "EmotionOntology":
        with path.open("r", encoding="utf-8") as stream:
            raw = yaml.safe_load(stream)
        return cls(EmotionOntologyDocument.model_validate(raw))

    @staticmethod
    def _normalize(value: str) -> str:
        return value.strip().casefold().replace(" ", "_")

    def resolve(self, label_or_alias: str) -> OntologyEmotion:
        normalized = self._normalize(label_or_alias)
        emotion_id = self._aliases.get(normalized)
        if emotion_id is None:
            raise UnknownEmotionError(
                f"emotion {label_or_alias!r} is not registered"
            )
        return self._emotions[emotion_id]

    def all(self) -> tuple[OntologyEmotion, ...]:
        return tuple(self._emotions[key] for key in sorted(self._emotions))

    def validate_state(self, state: EmotionState) -> None:
        families: set[str] = set()
        for field in ("primary", "secondary"):
            label = getattr(state, field)
            if label is not None:
                if label not in self._emotions:
                    raise UnknownEmotionError(f"{field} emotion {label!r} is not registered")
                families.update(self._emotions[label].families)
        if not state.families <= families:
            raise UnknownEmotionError("families do not belong to the supplied emotion labels")

    def __len__(self) -> int:
        return len(self._emotions)
