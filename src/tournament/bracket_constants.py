"""Shared constants for double-elimination bracket planning.

Keeping these values in one dependency-free module prevents the entry-mode and
bracket-side identifiers from drifting between seeding, match, and route logic.
"""

ENTRY_ALL_WINNERS = "all_winners"
ENTRY_SPLIT_BY_GROUP_SEED = "split_by_group_seed"

BRACKET_SIDE_WINNERS = "winners"
BRACKET_SIDE_LOSERS = "losers"
BRACKET_SIDE_FINALS = "finals"

MIN_BRACKET_SIZE = 4
MAX_BRACKET_SIZE = 32
