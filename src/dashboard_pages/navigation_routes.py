"""Stable internal URLs for dashboard detail navigation."""

from __future__ import annotations

from urllib.parse import quote


def player_profile_url(player_id: str) -> str:
    """Return the internal URL for one stable player identifier."""

    return f"/players?player_id={quote(str(player_id), safe='')}"


def tournament_archive_url(tournament_number: int) -> str:
    """Return the internal URL for one archived tournament number."""

    number = int(tournament_number)
    if number <= 0:
        raise ValueError("Tournament numbers must be positive.")
    return f"/tournaments?tournament={number}"
