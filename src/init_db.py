from __future__ import annotations

import argparse
import json
import sqlite3
import unicodedata
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = ROOT / "data" / "smash_wm.db"
DEFAULT_SCHEMA_PATH = ROOT / "src" / "schema.sql"
DEFAULT_SEED_PATH = ROOT / "data" / "private_seed.json"
DEFAULT_MIGRATIONS_DIR = ROOT / "src" / "migrations"


def normalize_alias(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return " ".join(normalized.strip().casefold().split())


def load_seed_data(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(
            f"Seed file not found: {path}\n"
            "Copy examples/seed.example.json to data/private_seed.json "
            "and replace the example records with your private data."
        )

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("The seed file must contain a JSON object.")
    if not isinstance(payload.get("players"), list):
        raise ValueError("The 'players' field must be a list.")
    if not isinstance(payload.get("tournaments"), list):
        raise ValueError("The 'tournaments' field must be a list.")
    return payload


def initialize_database(
    db_path: Path,
    schema_path: Path,
    seed_path: Path,
    *,
    replace: bool = False,
    migrations_dir: Path = DEFAULT_MIGRATIONS_DIR,
) -> None:
    if db_path.exists():
        if not replace:
            raise FileExistsError(
                f"Database already exists: {db_path}\n"
                "Use --replace to recreate it."
            )
        db_path.unlink()

    if not schema_path.exists():
        raise FileNotFoundError(f"Schema file not found: {schema_path}")
    if not migrations_dir.is_dir():
        raise FileNotFoundError(
            f"Migrations directory not found: {migrations_dir}"
        )

    seed = load_seed_data(seed_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    players = []
    aliases = []
    for player in seed["players"]:
        player_id = str(player["player_id"])
        display_name = str(player["display_name"])
        players.append((
            player_id,
            display_name,
            int(bool(player.get("core_player", False))),
            int(bool(player.get("active", True))),
            player.get("notes"),
        ))

        player_aliases = player.get("aliases", [display_name])
        if display_name not in player_aliases:
            player_aliases = [display_name, *player_aliases]
        for alias in dict.fromkeys(str(alias) for alias in player_aliases):
            aliases.append((player_id, alias, normalize_alias(alias)))

    tournaments = [
        (
            str(item["tournament_id"]),
            int(item["tournament_number"]),
            str(item["tournament_date"]),
            str(item["winner_id"]),
            str(item.get("bracket_source", "unknown")),
            int(bool(item.get("match_data_available", False))),
        )
        for item in seed["tournaments"]
    ]

    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(schema_path.read_text(encoding="utf-8"))
        for migration_path in sorted(migrations_dir.glob("*.sql")):
            connection.executescript(
                migration_path.read_text(encoding="utf-8")
            )
        connection.executemany(
            """
            INSERT INTO players(
                player_id, display_name, core_player, active, notes
            ) VALUES (?, ?, ?, ?, ?)
            """,
            players,
        )
        connection.executemany(
            """
            INSERT INTO player_aliases(
                player_id, alias, normalized_alias
            ) VALUES (?, ?, ?)
            """,
            aliases,
        )
        connection.executemany(
            """
            INSERT INTO tournaments(
                tournament_id, tournament_number, tournament_date,
                winner_id, bracket_source, match_data_available
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            tournaments,
        )

    print(f"Database created: {db_path}")
    print(f"Players: {len(players)}")
    print(f"Aliases: {len(aliases)}")
    print(f"Tournaments: {len(tournaments)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Initialize the Smash World Cup database from a private seed file."
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA_PATH)
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED_PATH)
    parser.add_argument("--replace", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        initialize_database(
            args.db, args.schema, args.seed, replace=args.replace
        )
    except (
        FileExistsError,
        FileNotFoundError,
        KeyError,
        TypeError,
        ValueError,
        sqlite3.Error,
        json.JSONDecodeError,
    ) as error:
        raise SystemExit(f"Initialization failed: {error}") from error


if __name__ == "__main__":
    main()
