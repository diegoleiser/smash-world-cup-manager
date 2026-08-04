#!/usr/bin/env python3
"""Stable public interface for generated dashboard narratives."""

from narrative_common import _sentence_count
from narrative_generators import (
    _overall_summary,
    generate_player_summary,
    generate_rivalry_summary,
    generate_tournament_preview,
    generate_tournament_summary,
)

__all__ = [
    "generate_player_summary",
    "generate_rivalry_summary",
    "generate_tournament_preview",
    "generate_tournament_summary",
]
