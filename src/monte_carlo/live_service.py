"""Read-only adapters between Tournament Manager drafts and live forecasts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import smash_statistics as stats
from db.connection import open_sqlite_connection
from monte_carlo.group_simulation import SimulationPlayer
from monte_carlo.bracket_continuation import (
    BracketContinuationForecast,
    BracketContinuationInput,
    forecast_bracket_continuation,
)
from monte_carlo.day_performance import estimate_group_day
from monte_carlo.live_group import (
    LiveGroupForecast,
    LiveGroupMatch,
    forecast_live_group,
)
from monte_carlo.model import CombinedModel
from tournament.bracket_constants import ENTRY_SPLIT_BY_GROUP_SEED
from tournament.drafts import FORMAT_GROUP_STAGE
from tournament.bracket_generation import (
    get_draft_bracket_matches,
    get_draft_bracket_routes,
)


@dataclass(frozen=True)
class LiveDraftGroupState:
    draft_id: str
    tournament_number: int
    group_id: str
    group_name: str
    players: tuple[SimulationPlayer, ...]
    matches: tuple[LiveGroupMatch, ...]


def load_live_draft_group_state(
    db_path: str | Path,
    draft_id: str,
) -> LiveDraftGroupState:
    """Load the current single-group production draft without modifying it."""

    elo_by_player_id = {
        str(row["player_id"]): float(row["elo"])
        for row in stats.get_elo_ranking(db_path, active_only=False)
    }
    with open_sqlite_connection(db_path) as connection:
        draft = connection.execute(
            """
            SELECT tournament_number, format_type, bracket_entry_mode
            FROM tournament_drafts
            WHERE draft_id = ?
            """,
            (draft_id,),
        ).fetchone()
        if draft is None:
            raise ValueError(f"Tournament draft not found: {draft_id}")
        if str(draft["format_type"]) != FORMAT_GROUP_STAGE:
            raise ValueError("Live Group forecasts require a Group Stage draft.")
        if str(draft["bracket_entry_mode"]) != ENTRY_SPLIT_BY_GROUP_SEED:
            raise ValueError(
                "The current Live Group forecast supports split bracket entry."
            )
        groups = connection.execute(
            """
            SELECT group_id, group_name
            FROM tournament_draft_groups
            WHERE draft_id = ?
            ORDER BY group_number
            """,
            (draft_id,),
        ).fetchall()
        if len(groups) != 1:
            raise ValueError(
                "The current Live Group forecast requires exactly one group."
            )
        group_id = str(groups[0]["group_id"])
        member_rows = connection.execute(
            """
            SELECT
                gm.player_id,
                p.display_name,
                dp.manual_seed
            FROM tournament_draft_group_members AS gm
            JOIN players AS p ON p.player_id = gm.player_id
            JOIN tournament_draft_participants AS dp
              ON dp.draft_id = ?
             AND dp.player_id = gm.player_id
            WHERE gm.group_id = ?
            ORDER BY dp.manual_seed, p.display_name COLLATE NOCASE
            """,
            (draft_id, group_id),
        ).fetchall()
        match_rows = connection.execute(
            """
            SELECT
                player_1_id,
                player_2_id,
                status,
                winner_id,
                player_1_score,
                player_2_score
            FROM tournament_draft_group_matches
            WHERE group_id = ?
            ORDER BY round_number, match_number
            """,
            (group_id,),
        ).fetchall()
    if not member_rows:
        raise ValueError("The draft group has no members.")
    if not match_rows:
        raise ValueError("Generate Group Stage Sets before forecasting.")
    players = tuple(
        SimulationPlayer(
            player_id=str(row["player_id"]),
            display_name=str(row["display_name"]),
            initial_seed=int(row["manual_seed"]),
            initial_elo=elo_by_player_id.get(str(row["player_id"]), 1000.0),
        )
        for row in member_rows
    )
    matches = tuple(
        LiveGroupMatch(
            player_1_id=str(row["player_1_id"]),
            player_2_id=str(row["player_2_id"]),
            status=str(row["status"]),
            winner_id=(
                str(row["winner_id"])
                if row["winner_id"] is not None
                else None
            ),
            player_1_score=(
                int(row["player_1_score"])
                if row["player_1_score"] is not None
                else None
            ),
            player_2_score=(
                int(row["player_2_score"])
                if row["player_2_score"] is not None
                else None
            ),
        )
        for row in match_rows
    )
    return LiveDraftGroupState(
        draft_id=draft_id,
        tournament_number=int(draft["tournament_number"]),
        group_id=group_id,
        group_name=str(groups[0]["group_name"]),
        players=players,
        matches=matches,
    )


def forecast_live_draft_group(
    db_path: str | Path,
    draft_id: str,
    model: CombinedModel,
    n_simulations: int,
    random_seed: int,
) -> LiveGroupForecast:
    """Load and forecast the current standard single-group draft."""

    state = load_live_draft_group_state(db_path, draft_id)
    if len(state.players) != 7:
        raise ValueError(
            "The current production Live Group forecast requires "
            "exactly seven players."
        )
    return forecast_live_group(
        list(state.players),
        list(state.matches),
        model,
        n_simulations,
        random_seed,
        winners_count=4,
    )


def load_draft_bracket_continuation(
    db_path: str | Path,
    draft_id: str,
) -> BracketContinuationInput:
    """Load persisted bracket rows, routes, and bracket-seed order."""

    matches = get_draft_bracket_matches(db_path, draft_id)
    routes = get_draft_bracket_routes(db_path, draft_id)
    if not matches:
        raise ValueError("Generate the Bracket before forecasting it.")
    with open_sqlite_connection(db_path) as connection:
        seed_rows = connection.execute(
            """
            SELECT player_id
            FROM tournament_draft_participants
            WHERE draft_id = ?
              AND bracket_seed IS NOT NULL
            ORDER BY bracket_seed
            """,
            (draft_id,),
        ).fetchall()
    seeded_player_ids = tuple(str(row["player_id"]) for row in seed_rows)
    if len(seeded_player_ids) != 7:
        raise ValueError(
            "The current production Bracket forecast requires seven players."
        )
    return BracketContinuationInput(
        matches=tuple(matches),
        routes=tuple(routes),
        seeded_player_ids=seeded_player_ids,
    )


def forecast_live_draft_bracket(
    db_path: str | Path,
    draft_id: str,
    model: CombinedModel,
    n_simulations: int,
    random_seed: int,
) -> BracketContinuationForecast:
    """Forecast a persisted partial bracket with frozen Group Day values."""

    group_state = load_live_draft_group_state(db_path, draft_id)
    day_posterior = estimate_group_day(
        [player.player_id for player in group_state.players],
        group_state.matches,
        model,
    )
    bracket_state = load_draft_bracket_continuation(db_path, draft_id)
    return forecast_bracket_continuation(
        bracket_state,
        model,
        day_posterior.values,
        n_simulations,
        random_seed,
    )
