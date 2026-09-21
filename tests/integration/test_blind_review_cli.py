import json
from pathlib import Path

from character_performance.cli.blind_review import prepare_review


ROOT = Path(__file__).parents[2]


def test_prepare_review_writes_public_packet_separate_from_answer_key(
    tmp_path: Path,
) -> None:
    packet_path, key_path = prepare_review(ROOT, tmp_path, seed=41)

    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    key = json.loads(key_path.read_text(encoding="utf-8"))
    public_text = packet_path.read_text(encoding="utf-8")

    assert packet["packet_id"] == key["packet_id"]
    assert len(packet["items"]) >= 900
    assert len({item["genre"] for item in packet["items"]}) >= 6
    assert "unit_ids" not in public_text
    assert "body.acknowledge_once" not in public_text
