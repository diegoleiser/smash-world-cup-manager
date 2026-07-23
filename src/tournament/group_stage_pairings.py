"""Deterministic Round Robin schedules for tournament groups."""

from __future__ import annotations


def generate_round_robin_pairings(
    player_ids: list[str],
) -> list[list[tuple[str, str]]]:
    """
    Generate one Round Robin schedule using the circle method.

    Every unordered player pair occurs exactly once. For an odd number of
    players, an internal ``None`` slot rotates through the schedule; the
    corresponding bye is omitted instead of becoming a persisted match.
    """

    if len(player_ids) < 2:
        raise ValueError(
            "At least two players are required for round-robin matches."
        )

    if len(player_ids) != len(set(player_ids)):
        raise ValueError("Each player may only appear once.")

    rotation: list[str | None] = list(player_ids)

    if len(rotation) % 2 == 1:
        rotation.append(None)

    player_count = len(rotation)
    round_count = player_count - 1
    matches_per_round = player_count // 2

    rounds: list[list[tuple[str, str]]] = []

    for round_index in range(round_count):
        round_pairings: list[tuple[str, str]] = []

        for pairing_index in range(matches_per_round):
            player_1 = rotation[pairing_index]
            player_2 = rotation[player_count - 1 - pairing_index]

            if player_1 is None or player_2 is None:
                continue

            # Alternating the display order avoids presenting the fixed player
            # in the same slot in every round. It does not affect standings.
            if round_index % 2 == 1:
                player_1, player_2 = player_2, player_1

            round_pairings.append(
                (
                    str(player_1),
                    str(player_2),
                )
            )

        rounds.append(round_pairings)

        # The first slot remains fixed; every other slot rotates clockwise.
        rotation = [
            rotation[0],
            rotation[-1],
            *rotation[1:-1],
        ]

    return rounds
