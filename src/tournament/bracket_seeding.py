"""Bracket sizing and deterministic seed-slot assignments."""

from __future__ import annotations

from tournament.bracket_constants import (
    BRACKET_SIDE_LOSERS,
    BRACKET_SIDE_WINNERS,
    MAX_BRACKET_SIZE,
    MIN_BRACKET_SIZE,
)


def get_bracket_size(participant_count: int) -> int:
    """
    Return the smallest supported power-of-two bracket size.

    Examples:
        3-4 players   -> 4
        5-8 players   -> 8
        9-16 players  -> 16
        17-32 players -> 32
    """
    if participant_count < 3:
        raise ValueError(
            "A double-elimination bracket requires at least 3 participants."
        )

    bracket_size = 1 << (participant_count - 1).bit_length()

    if bracket_size < MIN_BRACKET_SIZE:
        bracket_size = MIN_BRACKET_SIZE

    if bracket_size > MAX_BRACKET_SIZE:
        raise ValueError(
            f"Brackets larger than {MAX_BRACKET_SIZE} are not supported."
        )

    return bracket_size


def get_standard_seed_order(bracket_size: int) -> list[int]:
    """
    Return standard seeded bracket positions.

    The returned list is read in pairs.

    Example for an 8-player bracket:
        [1, 8, 4, 5, 2, 7, 3, 6]

    This creates:
        1 vs 8
        4 vs 5
        2 vs 7
        3 vs 6
    """
    if bracket_size < 2 or bracket_size & (bracket_size - 1):
        raise ValueError(
            "Bracket size must be a power of two."
        )

    seed_order = [1, 2]
    current_size = 2

    while current_size < bracket_size:
        next_size = current_size * 2
        seed_order = [
            seed
            for existing_seed in seed_order
            for seed in (
                existing_seed,
                next_size + 1 - existing_seed,
            )
        ]
        current_size = next_size

    return seed_order


def get_first_round_seed_pairs(
    bracket_size: int,
) -> list[tuple[int, int]]:
    """Pair adjacent positions from the standard seed ordering."""
    seed_order = get_standard_seed_order(bracket_size)

    return [
        (
            seed_order[index],
            seed_order[index + 1],
        )
        for index in range(0, len(seed_order), 2)
    ]


def get_split_bracket_seed_pairs(
    bracket_size: int,
) -> dict[str, list[tuple[int, int]]]:
    """
    Split a bracket so that the upper half starts in Winners
    and the lower half starts in Losers.

    Example for size 8:
        Winners: 1 vs 4, 2 vs 3
        Losers:  5 vs 8, 6 vs 7
    """
    if bracket_size < MIN_BRACKET_SIZE:
        raise ValueError(
            f"Bracket size must be at least {MIN_BRACKET_SIZE}."
        )

    if bracket_size & (bracket_size - 1):
        raise ValueError(
            "Bracket size must be a power of two."
        )

    half_size = bracket_size // 2
    half_seed_order = get_standard_seed_order(half_size)

    winners_pairs = [
        (
            half_seed_order[index],
            half_seed_order[index + 1],
        )
        for index in range(0, len(half_seed_order), 2)
    ]

    losers_seed_order = [
        seed + half_size
        for seed in half_seed_order
    ]

    losers_pairs = [
        (
            losers_seed_order[index],
            losers_seed_order[index + 1],
        )
        for index in range(0, len(losers_seed_order), 2)
    ]

    return {
        BRACKET_SIDE_WINNERS: winners_pairs,
        BRACKET_SIDE_LOSERS: losers_pairs,
    }
