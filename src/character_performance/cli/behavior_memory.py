"""Operational CLI for behavior-memory migration, backup and restore."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from character_performance.memory import LegacyHistoryMapping, SQLiteBehaviorMemory


def _load_mappings(path: Path) -> tuple[LegacyHistoryMapping, ...]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw_mappings = payload.get("mappings") if isinstance(payload, dict) else payload
    if not isinstance(raw_mappings, list):
        raise ValueError("mapping file must be a list or contain a mappings list")
    return tuple(LegacyHistoryMapping.model_validate(item) for item in raw_mappings)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cpp-behavior-memory",
        description="Manage cross-chapter behavior memory databases",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    migrate_parser = commands.add_parser(
        "migrate-legacy", description="Import explicitly mapped legacy history rows"
    )
    migrate_parser.add_argument("mapping", type=Path)
    migrate_parser.add_argument("--db", type=Path, required=True)

    backup_parser = commands.add_parser("backup", description="Create a verified backup")
    backup_parser.add_argument("--db", type=Path, required=True)
    backup_parser.add_argument("--output", type=Path, required=True)

    restore_parser = commands.add_parser("restore", description="Restore a verified backup")
    restore_parser.add_argument("backup", type=Path)
    restore_parser.add_argument("--db", type=Path, required=True)
    restore_parser.add_argument("--overwrite", action="store_true")
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    if args.command == "restore":
        memory = SQLiteBehaviorMemory.restore_backup(
            args.backup, args.db, overwrite=args.overwrite
        )
        try:
            print(json.dumps({"schema_version": memory.schema_version, "database": str(args.db)}))
        finally:
            memory.close()
        return

    if args.command == "backup" and not args.db.is_file():
        raise FileNotFoundError(f"behavior-memory database does not exist: {args.db}")
    mappings = _load_mappings(args.mapping) if args.command == "migrate-legacy" else None

    memory = SQLiteBehaviorMemory(args.db)
    try:
        if args.command == "backup":
            memory.backup(args.output)
            print(json.dumps({"backup": str(args.output)}))
            return
        occurrences = memory.import_legacy_history(mappings or ())
        print(
            json.dumps(
                {
                    "imported": len(occurrences),
                    "occurrence_ids": [item.occurrence_id for item in occurrences],
                },
                ensure_ascii=False,
            )
        )
    finally:
        memory.close()


if __name__ == "__main__":
    main()
