"""Shared deterministic selection helpers for generated narratives."""

from __future__ import annotations

import hashlib
import re


def _sentence_count(text: str) -> int:
    """Return the number of complete sentences in generated copy."""

    return len(re.findall(r"[.!?](?:\s|$)", text))


def _stable_variant(seed: str, *options: str) -> str:
    """Select a stable wording variant without changing between reruns."""

    if not options:
        raise ValueError("At least one wording option is required.")
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return options[int.from_bytes(digest[:4], "big") % len(options)]


def _select_preview_sentences(sentences: list[str]) -> list[str]:
    """Keep the preview concise while preserving distinct story angles."""

    if not sentences:
        return []

    selected = [sentences[0]]
    themes = (
        ("defending champion",),
        ("title race", "most decorated", "only active player"),
        ("recent set record", "strongest recent form"),
        ("trending upward", "dark horse"),
        ("poor form",),
        ("active winning streak",),
        ("rivalry to watch",),
        ("Their latest meeting",),
        ("wide open", "chasing field"),
    )

    for keywords in themes:
        candidate = next(
            (
                sentence
                for sentence in sentences[1:]
                if sentence not in selected
                and any(keyword in sentence for keyword in keywords)
            ),
            None,
        )
        if candidate is not None:
            selected.append(candidate)
        if len(selected) == 9:
            return selected

    for sentence in sentences[1:]:
        if sentence not in selected:
            selected.append(sentence)
        if len(selected) == 9:
            break

    return selected


def _select_tournament_sentences(sentences: list[str]) -> list[str]:
    """Select up to ten high-value tournament recap sentences."""

    if len(sentences) <= 10:
        return sentences

    priorities = {
        "defended the title": 100,
        "consecutive championship": 100,
        "World Championship title": 100,
        "first title since": 98,
        "same finalists": 95,
        "podium streak": 95,
        "career-high": 95,
        "recorded set wins": 95,
        "tournament appearance": 90,
        "biggest Elo upset": 90,
        "initial seed": 85,
        "previous appearance": 85,
        "title defence ended": 85,
        "Group Stage unbeaten": 80,
        "biggest Elo gain": 75,
        "led the field": 65,
        "players competed": 55,
    }
    ranked = sorted(
        enumerate(sentences[1:], start=1),
        key=lambda item: max(
            (
                score
                for phrase, score in priorities.items()
                if phrase in item[1]
            ),
            default=50,
        ),
        reverse=True,
    )[:9]
    selected_indexes = {0, *(index for index, _ in ranked)}
    return [
        sentence
        for index, sentence in enumerate(sentences)
        if index in selected_indexes
    ]
