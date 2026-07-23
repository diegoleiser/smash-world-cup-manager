"""Shared database access and player resolution for statistics services."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from db.connection import open_sqlite_connection


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "smash_wm.db"


class PlayerNotFoundError(ValueError):
    """Raised when a player cannot be found."""


def connect_db(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open the SQLite database with named columns."""

    return open_sqlite_connection(db_path)


def resolve_player(
    connection: sqlite3.Connection,
    player_reference: str,
) -> sqlite3.Row:
    """Find a player by ID or case-insensitive display name."""

    player = connection.execute(
        """
        SELECT
            player_id,
            display_name,
            core_player,
            active,
            notes
        FROM players
        WHERE player_id = ?
           OR lower(display_name) = lower(?)
        LIMIT 1
        """,
        (player_reference, player_reference),
    ).fetchone()

    if player is None:
        raise PlayerNotFoundError(
            f"Player not found: {player_reference}"
        )

    return player
