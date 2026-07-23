"""Reconstruct visual bracket data from archived tournament matches."""

from __future__ import annotations

import re
from typing import Any


def challonge_identifier_order(
    identifier: str | None,
) -> int:
    """Convert a Challonge match identifier into a sortable number."""

    if not identifier:
        return 999999

    value = str(identifier).strip().upper()

    if not value:
        return 999999

    order = 0

    for character in value:
        if not character.isalpha():
            return 999999

        order = (
            order * 26
            + ord(character)
            - ord("A")
            + 1
        )

    return order

def build_archived_bracket_matches(
    matches: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert archived knockout matches into bracket-card data."""

    manager_matches = [
        match
        for match in matches
        if match["stage"] == "bracket"
    ]

    if manager_matches:
        return _build_manager_bracket_matches(
            manager_matches
        )

    knockout_matches = [
        match
        for match in matches
        if match["stage"] == "knockout"
        and match["challonge_round"] is not None
    ]

    knockout_matches = sorted(
        knockout_matches,
        key=lambda match: (
            challonge_identifier_order(
                match.get("challonge_identifier")
            ),
            str(match["match_id"]),
        ),
    )

    if not knockout_matches:
        return []

    positive_rounds = sorted(
        {
            int(match["challonge_round"])
            for match in knockout_matches
            if int(match["challonge_round"]) > 0
        }
    )

    negative_rounds = sorted(
        {
            abs(int(match["challonge_round"]))
            for match in knockout_matches
            if int(match["challonge_round"]) < 0
        }
    )

    grand_final_round = (
        positive_rounds[-1]
        if positive_rounds
        else None
    )

    grand_final_matches = [
        match
        for match in knockout_matches
        if int(match["challonge_round"]) == grand_final_round
    ]

    grand_final_matches = sorted(
        grand_final_matches,
        key=lambda match: (
            challonge_identifier_order(
                match.get("challonge_identifier")
            ),
            int(match["suggested_play_order"])
            if match["suggested_play_order"] is not None
            else 999999,
            str(match["match_id"]),
        ),
    )

    grand_final_match_ids = {
        str(match["match_id"]): index
        for index, match in enumerate(
            grand_final_matches,
            start=1,
        )
    }

    winners_final_round = (
        positive_rounds[-2]
        if len(positive_rounds) >= 2
        else None
    )

    losers_final_round = (
        negative_rounds[-1]
        if negative_rounds
        else None
    )

    matches_per_round: dict[
        tuple[str, int],
        int,
    ] = {}

    bracket_matches: list[dict[str, Any]] = []

    for match in knockout_matches:
        challonge_round = int(
            match["challonge_round"]
        )

        if challonge_round == grand_final_round:
            bracket_side = "finals"
            round_number = 1

            final_index = grand_final_match_ids.get(
                str(match["match_id"]),
                1,
            )

            if final_index == 1:
                round_label = "Grand Final"
                match_type = "grand_final"
                match_code = "GF"
            else:
                round_label = "Grand Final Reset"
                match_type = "grand_final_reset"
                match_code = "GFR"

        elif challonge_round == winners_final_round:
            bracket_side = "winners"
            round_number = challonge_round
            round_label = "Winners Final"
            match_type = "winners_final"
            match_code = "WF"

        elif (
            challonge_round < 0
            and abs(challonge_round)
            == losers_final_round
        ):
            bracket_side = "losers"
            round_number = abs(challonge_round)
            round_label = "Losers Final"
            match_type = "losers_final"
            match_code = "LF"

        elif challonge_round > 0:
            bracket_side = "winners"
            round_number = challonge_round
            round_label = (
                f"Winners Round {round_number}"
            )
            match_type = "standard"
            match_code = ""

        else:
            bracket_side = "losers"
            round_number = abs(challonge_round)
            round_label = (
                f"Losers Round {round_number}"
            )
            match_type = "standard"
            match_code = ""

        round_key = (
            bracket_side,
            round_number,
        )

        match_number = (
            matches_per_round.get(round_key, 0)
            + 1
        )

        matches_per_round[round_key] = (
            match_number
        )

        if not match_code:
            prefix = (
                "W"
                if bracket_side == "winners"
                else "L"
            )

            match_code = (
                f"{prefix}{round_number}"
                f"M{match_number}"
            )

        if match["walkover"]:
            status = "forfeit"

        elif match["winner"]:
            status = "completed"

        else:
            status = "waiting"

        bracket_matches.append(
            {
                "bracket_match_id": str(
                    match["match_id"]
                ),
                "match_code": match_code,
                "bracket_side": bracket_side,
                "round_number": round_number,
                "match_number": match_number,
                "round_label": round_label,
                "match_type": match_type,
                "player_1_id": (
                    str(match["player_1_id"])
                    if match["player_1_id"] is not None
                    else None
                ),
                "player_1_name": match["player_1"],

                "player_2_id": (
                    str(match["player_2_id"])
                    if match["player_2_id"] is not None
                    else None
                ),
                "player_2_name": match["player_2"],

                "winner_id": (
                    str(match["winner_id"])
                    if match["winner_id"] is not None
                    else None
                ),
                "winner_name": match["winner"],
                "player_1_score": (
                    match["player_1_score"]
                    if match["score_known"]
                    else None
                ),
                "player_2_score": (
                    match["player_2_score"]
                    if match["score_known"]
                    else None
                ),
                "status": status,
            }
        )

    return bracket_matches


def _build_manager_bracket_matches(
    matches: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Restore structured Bracket fields saved in Tournament Manager labels.

    Tournament Manager archives a label such as
    ``Losers Round 3 (L3M1)`` instead of Challonge round metadata. The code
    suffix is sufficient to recover the original visual position.
    """

    parsed_matches: list[
        tuple[dict[str, Any], str, str]
    ] = []

    for match in matches:
        archived_label = str(
            match.get("round_label") or ""
        )
        code_match = re.search(
            r"\((W\d+M\d+|L\d+M\d+|WF|LF|GF|GFR)\)\s*$",
            archived_label,
        )

        if code_match is None:
            continue

        match_code = code_match.group(1)
        round_label = archived_label[
            :code_match.start()
        ].rstrip()
        parsed_matches.append(
            (match, match_code, round_label)
        )

    regular_winners_rounds = [
        int(code_match.group(1))
        for _, match_code, _ in parsed_matches
        if (
            code_match := re.fullmatch(
                r"W(\d+)M\d+",
                match_code,
            )
        )
    ]
    regular_losers_rounds = [
        int(code_match.group(1))
        for _, match_code, _ in parsed_matches
        if (
            code_match := re.fullmatch(
                r"L(\d+)M\d+",
                match_code,
            )
        )
    ]

    winners_final_round = (
        max(regular_winners_rounds, default=0) + 1
    )
    losers_final_round = (
        max(regular_losers_rounds, default=0) + 1
    )

    bracket_matches: list[dict[str, Any]] = []

    for match, match_code, round_label in parsed_matches:
        regular_match = re.fullmatch(
            r"([WL])(\d+)M(\d+)",
            match_code,
        )

        if regular_match is not None:
            bracket_side = (
                "winners"
                if regular_match.group(1) == "W"
                else "losers"
            )
            round_number = int(
                regular_match.group(2)
            )
            match_number = int(
                regular_match.group(3)
            )
            match_type = "standard"

        elif match_code == "WF":
            bracket_side = "winners"
            round_number = winners_final_round
            match_number = 1
            match_type = "winners_final"

        elif match_code == "LF":
            bracket_side = "losers"
            round_number = losers_final_round
            match_number = 1
            match_type = "losers_final"

        elif match_code == "GF":
            bracket_side = "finals"
            round_number = 1
            match_number = 1
            match_type = "grand_final"

        else:
            bracket_side = "finals"
            round_number = 2
            match_number = 1
            match_type = "grand_final_reset"

        bracket_matches.append(
            {
                "bracket_match_id": str(
                    match["match_id"]
                ),
                "match_code": match_code,
                "bracket_side": bracket_side,
                "round_number": round_number,
                "match_number": match_number,
                "round_label": (
                    round_label
                    or match_code
                ),
                "match_type": match_type,
                "player_1_id": match["player_1_id"],
                "player_1_name": match["player_1"],
                "player_2_id": match["player_2_id"],
                "player_2_name": match["player_2"],
                "winner_id": match["winner_id"],
                "winner_name": match["winner"],
                "player_1_score": (
                    match["player_1_score"]
                    if match["score_known"]
                    else None
                ),
                "player_2_score": (
                    match["player_2_score"]
                    if match["score_known"]
                    else None
                ),
                "status": (
                    "forfeit"
                    if match["walkover"]
                    else "completed"
                ),
            }
        )

    return sorted(
        bracket_matches,
        key=lambda match: (
            {
                "winners": 1,
                "losers": 2,
                "finals": 3,
            }.get(str(match["bracket_side"]), 4),
            int(match["round_number"]),
            int(match["match_number"]),
        ),
    )

def build_archived_bracket_routes(
    matches: list[dict[str, Any]],
    bracket_matches: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Reconstruct bracket routes from later player appearances."""

    knockout_matches = [
        match
        for match in matches
        if (
            (
                match["stage"] == "knockout"
                and match["challonge_round"] is not None
            )
            or match["stage"] == "bracket"
        )
    ]

    if not knockout_matches or not bracket_matches:
        return []

    bracket_code_by_match_id = {
        str(match["bracket_match_id"]): str(
            match["match_code"]
        )
        for match in bracket_matches
    }

    def play_order(
        match: dict[str, Any],
    ) -> tuple[int, str]:
        return (
            int(match["suggested_play_order"])
            if match["suggested_play_order"] is not None
            else 999999,
            str(match["match_id"]),
        )

    ordered_matches = sorted(
        knockout_matches,
        key=play_order,
    )

    routes: list[dict[str, Any]] = []
    existing_routes: set[
        tuple[str, str, str, int]
    ] = set()

    for source_index, source_match in enumerate(
        ordered_matches
    ):
        source_code = bracket_code_by_match_id.get(
            str(source_match["match_id"])
        )

        if source_code is None:
            continue

        winner_name = (
            str(source_match["winner"])
            if source_match["winner"]
            else None
        )

        player_1_name = str(
            source_match["player_1"]
        )
        player_2_name = str(
            source_match["player_2"]
        )

        loser_name: str | None = None

        if winner_name == player_1_name:
            loser_name = player_2_name

        elif winner_name == player_2_name:
            loser_name = player_1_name

        outcomes = [
            ("winner", winner_name),
            ("loser", loser_name),
        ]

        for source_outcome, advancing_player in outcomes:
            if advancing_player is None:
                continue

            target_match = next(
                (
                    later_match
                    for later_match
                    in ordered_matches[source_index + 1:]
                    if advancing_player
                    in {
                        str(later_match["player_1"]),
                        str(later_match["player_2"]),
                    }
                ),
                None,
            )

            if target_match is None:
                continue

            target_code = bracket_code_by_match_id.get(
                str(target_match["match_id"])
            )

            if target_code is None:
                continue

            if (
                source_code == "GF"
                and target_code == "GFR"
                and source_outcome == "loser"
            ):
                continue

            if advancing_player == str(
                target_match["player_1"]
            ):
                target_slot = 1

            elif advancing_player == str(
                target_match["player_2"]
            ):
                target_slot = 2

            else:
                continue

            route_key = (
                source_code,
                source_outcome,
                target_code,
                target_slot,
            )

            if route_key in existing_routes:
                continue

            routes.append(
                {
                    "source_code": source_code,
                    "source_outcome": source_outcome,
                    "target_code": target_code,
                    "target_slot": target_slot,
                }
            )

            existing_routes.add(route_key)

    return routes

def archived_match_round_label(
    match: dict[str, Any],
    bracket_matches: list[dict[str, Any]],
) -> str:
    """Return a readable round label for an archived match."""

    if match["stage"] != "knockout":
        return str(
            match["round_label"]
            or match["challonge_round"]
            or "–"
        )

    archived_match = next(
        (
            bracket_match
            for bracket_match in bracket_matches
            if str(bracket_match["bracket_match_id"])
            == str(match["match_id"])
        ),
        None,
    )

    if archived_match is not None:
        return str(archived_match["round_label"])

    return str(
        match["round_label"]
        or match["challonge_round"]
        or "–"
    )
