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
from monte_carlo.live_multi_group import (
    LiveGroupPool,
    forecast_live_groups,
)
from monte_carlo.model import CombinedModel
from tournament.bracket_constants import ENTRY_SPLIT_BY_GROUP_SEED
from tournament.bracket_seeding import get_bracket_size
from tournament.drafts import (
    FORMAT_DOUBLE_ELIMINATION,
    FORMAT_GROUP_STAGE,
)
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


def load_live_draft_group_states(
    db_path: str | Path,
    draft_id: str,
) -> tuple[LiveDraftGroupState, ...]:
    """Load every draft group without modifying tournament state."""

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
        if not groups:
            raise ValueError("Create tournament groups before forecasting.")
        states = []
        for group in groups:
            group_id = str(group["group_id"])
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
                raise ValueError("A draft group has no members.")
            if not match_rows:
                raise ValueError(
                    "Generate Group Stage Sets before forecasting."
                )
            states.append(
                LiveDraftGroupState(
                    draft_id=draft_id,
                    tournament_number=int(draft["tournament_number"]),
                    group_id=group_id,
                    group_name=str(group["group_name"]),
                    players=tuple(
                        SimulationPlayer(
                            player_id=str(row["player_id"]),
                            display_name=str(row["display_name"]),
                            initial_seed=int(row["manual_seed"]),
                            initial_elo=elo_by_player_id.get(
                                str(row["player_id"]),
                                1000.0,
                            ),
                        )
                        for row in member_rows
                    ),
                    matches=tuple(
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
                    ),
                )
            )
    return tuple(states)


def load_live_draft_group_state(
    db_path: str | Path,
    draft_id: str,
) -> LiveDraftGroupState:
    """Load one group for callers that explicitly require a single group."""

    states = load_live_draft_group_states(db_path, draft_id)
    if len(states) != 1:
        raise ValueError("This operation requires exactly one group.")
    return states[0]


def forecast_live_draft_group(
    db_path: str | Path,
    draft_id: str,
    model: CombinedModel,
    n_simulations: int,
    random_seed: int,
) -> LiveGroupForecast:
    """Load and forecast the current standard single-group draft."""

    states = load_live_draft_group_states(db_path, draft_id)
    players = [player for state in states for player in state.players]
    model = model.with_neutral_players(
        {
            player.player_id: player.display_name
            for player in players
        }
    )
    if len(states) > 1:
        return forecast_live_groups(
            [
                LiveGroupPool(
                    group_id=state.group_id,
                    group_name=state.group_name,
                    players=state.players,
                    matches=state.matches,
                )
                for state in states
            ],
            model,
            n_simulations,
            random_seed,
        )
    state = states[0]
    bracket_size = get_bracket_size(len(state.players))
    return forecast_live_group(
        list(state.players),
        list(state.matches),
        model,
        n_simulations,
        random_seed,
        winners_count=bracket_size // 2,
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
    get_bracket_size(len(seeded_player_ids))
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
    """Forecast a persisted bracket with Group Day or neutral Day values."""

    bracket_state = load_draft_bracket_continuation(db_path, draft_id)
    with open_sqlite_connection(db_path) as connection:
        draft = connection.execute(
            """
            SELECT format_type
            FROM tournament_drafts
            WHERE draft_id = ?
            """,
            (draft_id,),
        ).fetchone()
        if draft is None:
            raise ValueError(f"Tournament draft not found: {draft_id}")
        player_rows = connection.execute(
            """
            SELECT dp.player_id, p.display_name
            FROM tournament_draft_participants AS dp
            JOIN players AS p ON p.player_id = dp.player_id
            WHERE dp.draft_id = ?
              AND dp.bracket_seed IS NOT NULL
            ORDER BY dp.bracket_seed
            """,
            (draft_id,),
        ).fetchall()
    player_names = {
        str(row["player_id"]): str(row["display_name"])
        for row in player_rows
    }
    model = model.with_neutral_players(player_names)
    format_type = str(draft["format_type"])
    if format_type == FORMAT_GROUP_STAGE:
        group_states = load_live_draft_group_states(db_path, draft_id)
        players = [
            player for state in group_states for player in state.players
        ]
        matches = [
            match for state in group_states for match in state.matches
        ]
        day_values = estimate_group_day(
            [player.player_id for player in players],
            matches,
            model,
        ).values
    elif format_type == FORMAT_DOUBLE_ELIMINATION:
        day_values = {
            player_id: 0.0
            for player_id in bracket_state.seeded_player_ids
        }
    else:
        raise ValueError(f"Unsupported tournament format: {format_type}")
    return forecast_bracket_continuation(
        bracket_state,
        model,
        day_values,
        n_simulations,
        random_seed,
    )
