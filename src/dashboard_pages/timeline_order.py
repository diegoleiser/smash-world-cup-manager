"""Pure ordering helpers shared by dashboard timeline charts."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def chronological_tournament_labels(
    rows: Iterable[Mapping[str, Any]],
) -> list[str]:
    """Return unique tournament labels ordered by date and then number."""

    tournaments: dict[str, tuple[str, int]] = {}

    for row in rows:
        label = str(row["tournament"])
        tournament_date = row.get("tournament_date")
        date_key = (
            str(tournament_date)
            if tournament_date
            else "9999-12-31"
        )
        tournaments[label] = (
            date_key,
            int(row["tournament_number"]),
        )

    return [
        label
        for label, _ in sorted(
            tournaments.items(),
            key=lambda item: item[1],
        )
    ]
