"""Propagate resolved matches through a draft bracket."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from db.connection import open_sqlite_connection

connect_db = open_sqlite_connection


def _is_resolved_bracket_source(
    status: str,
    player_1_id: Any,
    player_2_id: Any,
) -> bool:
    """
    Return whether a source can no longer produce an undecided outcome.

    A Cancelled match is resolved without producing a player. If the other
    incoming route does produce a player, the target becomes an automatic Bye.
    """

    return status in {
        "completed",
        "forfeit",
        "bye",
        "cancelled",
    }


def _get_routed_bracket_player_id(
    *,
    source_outcome: str,
    player_1_id: Any,
    player_2_id: Any,
    winner_id: Any,
) -> str | None:
    """Return the player supplied by one resolved Bracket route."""

    if source_outcome == "winner":
        return (
            str(winner_id)
            if winner_id is not None
            else None
        )

    if (
        player_1_id is None
        or player_2_id is None
        or winner_id is None
    ):
        return None

    return str(
        player_2_id
        if winner_id == player_1_id
        else player_1_id
    )


def _get_cancelled_losers_advancer_id(
    *,
    source_outcome: str,
    bracket_side: str,
    player_1_id: Any,
    player_2_id: Any,
    player_1_seed: Any,
    player_2_seed: Any,
) -> str | None:
    """
    Return the better-seeded player for placement propagation.

    A real cancelled Losers match eliminates both players. The worse-seeded
    player is placed in the cancelled round, while the better-seeded player
    occupies the next round's placement and loses there automatically.
    """

    if (
        source_outcome != "winner"
        or bracket_side != "losers"
        or player_1_id is None
        or player_2_id is None
        or player_1_seed is None
        or player_2_seed is None
    ):
        return None

    return str(
        player_1_id
        if int(player_1_seed) < int(player_2_seed)
        else player_2_id
    )


def propagate_draft_bracket_results(
    db_path: str | Path,
    draft_id: str,
) -> list[dict[str, Any]]:
    """
    Propagate all decided bracket matches through their routes.

    The function is idempotent: it can safely be called again after
    every saved result.

    Once all incoming routes of a target match are resolved:
    - two players -> pending
    - one player  -> bye
    - no players  -> cancelled

    Grand Final Reset is handled separately.
    """

    terminal_target_statuses = {
        "completed",
        "forfeit",
        "bye",
        "cancelled",
    }

    changes: list[dict[str, Any]] = []

    with connect_db(db_path) as connection:
        while True:
            iteration_changed = False

            routes = connection.execute(
                """
                SELECT
                    r.source_outcome,
                    r.target_slot,

                    source.bracket_match_id
                        AS source_match_id,
                    source.match_code
                        AS source_code,
                    source.player_1_id
                        AS source_player_1_id,
                    source.player_2_id
                        AS source_player_2_id,
                    source.winner_id
                        AS source_winner_id,
                    source.status
                        AS source_status,
                    source.bracket_side
                        AS source_bracket_side,
                    source_player_1.bracket_seed
                        AS source_player_1_seed,
                    source_player_2.bracket_seed
                        AS source_player_2_seed,

                    target.bracket_match_id
                        AS target_match_id,
                    target.match_code
                        AS target_code,
                    target.player_1_id
                        AS target_player_1_id,
                    target.player_2_id
                        AS target_player_2_id,
                    target.status
                        AS target_status,
                    target.match_type
                        AS target_match_type
                FROM tournament_draft_bracket_routes AS r
                JOIN tournament_draft_bracket_matches AS source
                  ON source.bracket_match_id = r.source_match_id
                JOIN tournament_draft_bracket_matches AS target
                  ON target.bracket_match_id = r.target_match_id
                LEFT JOIN tournament_draft_participants
                    AS source_player_1
                  ON source_player_1.draft_id = r.draft_id
                 AND source_player_1.player_id =
                     source.player_1_id
                LEFT JOIN tournament_draft_participants
                    AS source_player_2
                  ON source_player_2.draft_id = r.draft_id
                 AND source_player_2.player_id =
                     source.player_2_id
                WHERE r.draft_id = ?
                ORDER BY
                    target.round_number,
                    target.match_number,
                    r.target_slot
                """,
                (draft_id,),
            ).fetchall()

            for route in routes:
                source_status = str(route["source_status"])

                if not _is_resolved_bracket_source(
                    source_status,
                    route["source_player_1_id"],
                    route["source_player_2_id"],
                ):
                    continue

                routed_player_id = (
                    _get_routed_bracket_player_id(
                        source_outcome=str(
                            route["source_outcome"]
                        ),
                        player_1_id=route[
                            "source_player_1_id"
                        ],
                        player_2_id=route[
                            "source_player_2_id"
                        ],
                        winner_id=route[
                            "source_winner_id"
                        ],
                    )
                )

                if (
                    routed_player_id is None
                    and source_status == "cancelled"
                ):
                    routed_player_id = (
                        _get_cancelled_losers_advancer_id(
                            source_outcome=str(
                                route["source_outcome"]
                            ),
                            bracket_side=str(
                                route["source_bracket_side"]
                            ),
                            player_1_id=route[
                                "source_player_1_id"
                            ],
                            player_2_id=route[
                                "source_player_2_id"
                            ],
                            player_1_seed=route[
                                "source_player_1_seed"
                            ],
                            player_2_seed=route[
                                "source_player_2_seed"
                            ],
                        )
                    )

                target_slot_column = (
                    "player_1_id"
                    if int(route["target_slot"]) == 1
                    else "player_2_id"
                )

                current_target_player = (
                    route["target_player_1_id"]
                    if int(route["target_slot"]) == 1
                    else route["target_player_2_id"]
                )

                if (
                    current_target_player is not None
                    and routed_player_id is not None
                    and str(current_target_player)
                    != routed_player_id
                ):
                    raise ValueError(
                        "Bracket route conflict: "
                        f"{route['target_code']} slot "
                        f"{route['target_slot']} already contains "
                        f"a different player."
                    )

                if (
                    current_target_player is None
                    and routed_player_id is not None
                ):
                    connection.execute(
                        f"""
                        UPDATE tournament_draft_bracket_matches
                        SET
                            {target_slot_column} = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE bracket_match_id = ?
                        """,
                        (
                            routed_player_id,
                            route["target_match_id"],
                        ),
                    )

                    changes.append(
                        {
                            "source_code": str(
                                route["source_code"]
                            ),
                            "source_outcome": str(
                                route["source_outcome"]
                            ),
                            "target_code": str(
                                route["target_code"]
                            ),
                            "target_slot": int(
                                route["target_slot"]
                            ),
                            "player_id": routed_player_id,
                        }
                    )

                    iteration_changed = True

            target_matches = connection.execute(
                """
                SELECT DISTINCT
                    target.bracket_match_id,
                    target.match_code,
                    target.match_type,
                    target.player_1_id,
                    target.player_2_id,
                    target.winner_id,
                    target.status
                FROM tournament_draft_bracket_routes AS r
                JOIN tournament_draft_bracket_matches AS target
                  ON target.bracket_match_id = r.target_match_id
                WHERE r.draft_id = ?
                """,
                (draft_id,),
            ).fetchall()

            for target in target_matches:
                if (
                    target["match_type"]
                    == "grand_final_reset"
                ):
                    continue

                current_target_status = str(
                    target["status"]
                )

                if current_target_status in terminal_target_statuses:
                    continue

                incoming_sources = connection.execute(
                    """
                    SELECT
                        source.status,
                        source.player_1_id,
                        source.player_2_id,
                        source.winner_id,
                        source.bracket_side,
                        source_player_1.bracket_seed
                            AS player_1_seed,
                        source_player_2.bracket_seed
                            AS player_2_seed,
                        r.source_outcome,
                        r.target_slot
                    FROM tournament_draft_bracket_routes AS r
                    JOIN tournament_draft_bracket_matches AS source
                      ON source.bracket_match_id =
                         r.source_match_id
                    LEFT JOIN tournament_draft_participants
                        AS source_player_1
                      ON source_player_1.draft_id = r.draft_id
                     AND source_player_1.player_id =
                         source.player_1_id
                    LEFT JOIN tournament_draft_participants
                        AS source_player_2
                      ON source_player_2.draft_id = r.draft_id
                     AND source_player_2.player_id =
                         source.player_2_id
                    WHERE r.target_match_id = ?
                    """,
                    (target["bracket_match_id"],),
                ).fetchall()

                all_sources_resolved = (
                    bool(incoming_sources)
                    and all(
                        _is_resolved_bracket_source(
                            str(source["status"]),
                            source["player_1_id"],
                            source["player_2_id"],
                        )
                        for source in incoming_sources
                    )
                )

                if not all_sources_resolved:
                    continue

                player_1_id = target["player_1_id"]
                player_2_id = target["player_2_id"]

                # A source may have become a Bye earlier in this same pass.
                # Its winner is not written into the target until the next
                # routing pass. Do not decide the target from a stale empty
                # slot in the meantime.
                all_routed_players_applied = all(
                    (
                        (
                            _get_routed_bracket_player_id(
                                source_outcome=str(
                                    source["source_outcome"]
                                ),
                                player_1_id=source["player_1_id"],
                                player_2_id=source["player_2_id"],
                                winner_id=source["winner_id"],
                            )
                            or (
                                _get_cancelled_losers_advancer_id(
                                    source_outcome=str(
                                        source["source_outcome"]
                                    ),
                                    bracket_side=str(
                                        source["bracket_side"]
                                    ),
                                    player_1_id=source[
                                        "player_1_id"
                                    ],
                                    player_2_id=source[
                                        "player_2_id"
                                    ],
                                    player_1_seed=source[
                                        "player_1_seed"
                                    ],
                                    player_2_seed=source[
                                        "player_2_seed"
                                    ],
                                )
                                if str(source["status"])
                                == "cancelled"
                                else None
                            )
                        )
                        is None
                    )
                    or (
                        player_1_id is not None
                        if int(source["target_slot"]) == 1
                        else player_2_id is not None
                    )
                    for source in incoming_sources
                )

                if not all_routed_players_applied:
                    continue

                if (
                    player_1_id is not None
                    and player_2_id is not None
                ):
                    cancelled_advancer_slots = [
                        int(source["target_slot"])
                        for source in incoming_sources
                        if (
                            str(source["status"]) == "cancelled"
                            and _get_cancelled_losers_advancer_id(
                                source_outcome=str(
                                    source["source_outcome"]
                                ),
                                bracket_side=str(
                                    source["bracket_side"]
                                ),
                                player_1_id=source[
                                    "player_1_id"
                                ],
                                player_2_id=source[
                                    "player_2_id"
                                ],
                                player_1_seed=source[
                                    "player_1_seed"
                                ],
                                player_2_seed=source[
                                    "player_2_seed"
                                ],
                            )
                            is not None
                        )
                    ]

                    if len(cancelled_advancer_slots) == 1:
                        new_status = "forfeit"
                        winner_id = (
                            player_2_id
                            if cancelled_advancer_slots[0] == 1
                            else player_1_id
                        )
                        completed_at_sql = "CURRENT_TIMESTAMP"
                    else:
                        new_status = "pending"
                        winner_id = None
                        completed_at_sql = "NULL"

                elif player_1_id is not None:
                    new_status = "bye"
                    winner_id = player_1_id
                    completed_at_sql = "CURRENT_TIMESTAMP"

                elif player_2_id is not None:
                    new_status = "bye"
                    winner_id = player_2_id
                    completed_at_sql = "CURRENT_TIMESTAMP"

                else:
                    new_status = "cancelled"
                    winner_id = None
                    completed_at_sql = "CURRENT_TIMESTAMP"

                if (
                    str(target["status"]) != new_status
                    or target["winner_id"] != winner_id
                ):
                    connection.execute(
                        f"""
                        UPDATE tournament_draft_bracket_matches
                        SET
                            winner_id = ?,
                            status = ?,
                            completed_at = {completed_at_sql},
                            updated_at = CURRENT_TIMESTAMP
                        WHERE bracket_match_id = ?
                        """,
                        (
                            winner_id,
                            new_status,
                            target["bracket_match_id"],
                        ),
                    )

                    iteration_changed = True

            if not iteration_changed:
                break

    return changes
