"""Backward-compatible public facade for bracket-planning helpers.

Callers may continue importing from this module while the implementation stays
separated into constants, seeding, match metadata, and route metadata. New code
may import the narrower modules when that makes its dependency clearer.
"""

from tournament.bracket_constants import (
    BRACKET_SIDE_FINALS,
    BRACKET_SIDE_LOSERS,
    BRACKET_SIDE_WINNERS,
    ENTRY_ALL_WINNERS,
    ENTRY_SPLIT_BY_GROUP_SEED,
    MAX_BRACKET_SIZE,
    MIN_BRACKET_SIZE,
)
from tournament.bracket_matches import (
    build_all_winners_bracket_plan,
    build_bracket_plan,
    build_split_bracket_plan,
)
from tournament.bracket_routes import (
    build_all_winners_route_plan,
    build_bracket_route_plan,
    build_split_bracket_route_plan,
)
from tournament.bracket_seeding import (
    get_bracket_size,
    get_first_round_seed_pairs,
    get_split_bracket_seed_pairs,
    get_standard_seed_order,
)

__all__ = [
    "BRACKET_SIDE_FINALS",
    "BRACKET_SIDE_LOSERS",
    "BRACKET_SIDE_WINNERS",
    "ENTRY_ALL_WINNERS",
    "ENTRY_SPLIT_BY_GROUP_SEED",
    "MAX_BRACKET_SIZE",
    "MIN_BRACKET_SIZE",
    "build_all_winners_bracket_plan",
    "build_all_winners_route_plan",
    "build_bracket_plan",
    "build_bracket_route_plan",
    "build_split_bracket_plan",
    "build_split_bracket_route_plan",
    "get_bracket_size",
    "get_first_round_seed_pairs",
    "get_split_bracket_seed_pairs",
    "get_standard_seed_order",
]
