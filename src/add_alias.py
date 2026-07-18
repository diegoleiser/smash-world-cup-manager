from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from challonge_import import DB_PATH, normalize_alias


def main() -> None:
    parser = argparse.ArgumentParser(description="Add player alias")
    parser.add_argument("player_id")
    parser.add_argument("alias")
    args = parser.parse_args()

    connection = sqlite3.connect(DB_PATH)
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        with connection:
            connection.execute(
                """
                INSERT INTO player_aliases(player_id, alias, normalized_alias)
                VALUES (?, ?, ?)
                """,
                (args.player_id, args.alias, normalize_alias(args.alias)),
            )
    except sqlite3.IntegrityError as exc:
        raise SystemExit(f"Alias could not be saved: {exc}") from exc
    finally:
        connection.close()

    print(f"Alias {args.alias!r} -> {args.player_id!r} saved.")


if __name__ == "__main__":
    main()
