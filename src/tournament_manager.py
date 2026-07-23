#!/usr/bin/env python3
"""Create and manage Smash World Championship tournament drafts."""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path
from typing import Any
import smash_statistics as stats
from db.connection import open_sqlite_connection
from tournament.bracket_planning import (
    BRACKET_SIDE_FINALS,
    BRACKET_SIDE_LOSERS,
    BRACKET_SIDE_WINNERS,
    ENTRY_ALL_WINNERS,
    ENTRY_SPLIT_BY_GROUP_SEED,
    MAX_BRACKET_SIZE,
    MIN_BRACKET_SIZE,
    build_all_winners_bracket_plan,
    build_all_winners_route_plan,
    build_bracket_plan,
    build_bracket_route_plan,
    build_split_bracket_plan,
    build_split_bracket_route_plan,
    get_bracket_size,
    get_first_round_seed_pairs,
    get_split_bracket_seed_pairs,
    get_standard_seed_order,
)
from tournament.group_stage_pairings import (
    generate_round_robin_pairings,
)
from tournament.group_stage_ranking import (
    build_global_group_ranking,
)
from tournament.group_stage_standings import (
    GROUP_MATCH_CANCELLED,
    GROUP_MATCH_COMPLETED,
    GROUP_MATCH_FORFEIT,
    GROUP_MATCH_PENDING,
    VALID_GROUP_MATCH_STATUSES,
    calculate_group_standings,
)
from tournament.group_stage_service import (
    create_draft_group_matches,
    create_draft_groups,
    get_draft_global_group_ranking,
    get_draft_group_matches,
    get_draft_group_standings,
    get_draft_groups,
    move_draft_group_member,
    reset_draft_group_matches,
    reset_draft_groups,
    update_draft_group_match,
)


FORMAT_GROUP_STAGE = "group_stage_double_elimination"
FORMAT_DOUBLE_ELIMINATION = "double_elimination"

VALID_FORMATS = {
    FORMAT_GROUP_STAGE,
    FORMAT_DOUBLE_ELIMINATION,
}

VALID_ENTRY_MODES = {
    ENTRY_ALL_WINNERS,
    ENTRY_SPLIT_BY_GROUP_SEED,
}

VALID_START_POSITIONS = {
    "winners",
    "losers",
}

BRACKET_START_ALL_WINNERS = "all_winners"
BRACKET_START_SPLIT = "split_by_group_seed"


from tournament.bracket_generation import (
    create_draft_bracket_matches,
    create_draft_bracket_routes,
    generate_draft_bracket as _generate_draft_bracket,
    get_draft_bracket_matches,
    get_draft_bracket_routes,
    get_draft_bracket_state,
    reset_draft_bracket,
    seed_draft_bracket_matches,
)


def generate_draft_bracket(
    db_path: str | Path,
    draft_id: str,
) -> dict[str, Any]:
    """Generate a bracket using the current draft seed snapshot rules."""

    return _generate_draft_bracket(
        db_path,
        draft_id,
        create_seed_snapshot=create_draft_bracket_seed_snapshot,
    )


from tournament.finalization import (
    finalize_draft_tournament,
    get_draft_finalization_preview,
)


from tournament.legacy_split_bracket import (
    create_draft_split_bracket_matches,
    create_draft_split_bracket_routes,
    seed_draft_split_bracket_matches,
)

from tournament.bracket_finalization import (
    get_draft_bracket_champion,
    sync_draft_grand_final_reset,
)
from tournament.bracket_progression import (
    propagate_draft_bracket_results,
)
from tournament.bracket_results import (
    reset_draft_bracket_match_result,
    update_draft_bracket_match,
)


def connect_db(db_path: str | Path) -> sqlite3.Connection:
    """Opens the SQLite database with foreign keys enabled."""

    return open_sqlite_connection(db_path)

from tournament.drafts import (
    create_draft,
    delete_draft,
    get_draft,
    list_drafts,
    update_draft_date,
    validate_draft_configuration,
)
from tournament.participants import (
    _draft_has_group_matches,
    add_participant,
    create_player,
    create_player_and_add_to_draft,
    remove_participant,
    update_participant,
)
from tournament.seeding import (
    apply_automatic_seeding,
    assign_manual_seeds,
    create_draft_bracket_seed_snapshot as _create_seed_snapshot,
    get_automatic_seed_order,
    save_participant_order,
)


def create_draft_bracket_seed_snapshot(
    db_path: str | Path,
    draft_id: str,
) -> list[dict[str, Any]]:
    """Persist final seeds using the current group-ranking service."""

    return _create_seed_snapshot(
        db_path,
        draft_id,
        get_global_group_ranking=get_draft_global_group_ranking,
    )
