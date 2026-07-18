from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "smash_wm.db"
RAW_DIR = ROOT / "data" / "raw"
API_BASE = "https://api.challonge.com/v1"


def normalize_alias(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    return " ".join(value.strip().casefold().split())


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class ParsedScore:
    player_1_score: int | None
    player_2_score: int | None
    known: bool


def parse_score(raw_score: Any, winner_present: bool) -> ParsedScore:
    """Parse Challonge scores and treat winner-marked 0-0 as unknown."""
    if raw_score is None:
        return ParsedScore(None, None, False)

    if isinstance(raw_score, (list, tuple)) and len(raw_score) == 2:
        try:
            left, right = int(raw_score[0]), int(raw_score[1])
        except (TypeError, ValueError):
            return ParsedScore(None, None, False)
    else:
        match = re.fullmatch(r"\s*(-?\d+)\s*[-–:]\s*(-?\d+)\s*", str(raw_score))
        if not match:
            return ParsedScore(None, None, False)
        left, right = int(match.group(1)), int(match.group(2))

    if winner_present and left == 0 and right == 0:
        return ParsedScore(None, None, False)
    if left < 0 or right < 0:
        return ParsedScore(None, None, False)
    return ParsedScore(left, right, True)


def unwrap_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return payload["data"]
    if isinstance(payload, list):
        return payload
    raise ValueError("Unerwartetes Challonge-JSON-Format")


def attributes(item: dict[str, Any], wrapper: str) -> dict[str, Any]:
    """Support both Challonge v1 wrappers and v2-style attributes."""
    wrapped = item.get(wrapper)
    if isinstance(wrapped, dict):
        return wrapped
    attrs = item.get("attributes")
    if isinstance(attrs, dict):
        return attrs
    return item


def load_alias_map(connection: sqlite3.Connection) -> dict[str, str]:
    return {
        row["normalized_alias"]: row["player_id"]
        for row in connection.execute(
            "SELECT normalized_alias, player_id FROM player_aliases"
        )
    }


def ensure_match_columns(connection: sqlite3.Connection) -> None:
    """Add source-detail columns to databases created with the older schema."""
    existing = {
        row["name"] for row in connection.execute("PRAGMA table_info(matches)")
    }
    additions = {
        "stage": "TEXT",
        "challonge_match_id": "TEXT",
        "challonge_identifier": "TEXT",
        "challonge_group_id": "TEXT",
        "challonge_round": "INTEGER",
        "suggested_play_order": "INTEGER",
        "completed_at": "TEXT",
    }
    for name, sql_type in additions.items():
        if name not in existing:
            connection.execute(f"ALTER TABLE matches ADD COLUMN {name} {sql_type}")


def fetch_json(tournament_ref: str, endpoint: str) -> Any:
    if requests is None:
        raise RuntimeError("The 'requests' package is missing: python -m pip install requests")

    load_env_file(ROOT / ".env")
    api_key = os.environ.get("CHALLONGE_API_KEY")
    if not api_key:
        raise RuntimeError("CHALLONGE_API_KEY is missing. See .env.example.")

    session = requests.Session()
    session.trust_env = False
    url = f"{API_BASE}/tournaments/{tournament_ref}/{endpoint}.json"
    response = session.get(
        url,
        params={"api_key": api_key},
        headers={
            "Accept": "application/json",
            "User-Agent": "curl/8.7.1",
            "Connection": "close",
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def save_raw(tournament_id: str, participants: Any, matches: Any) -> tuple[Path, Path]:
    directory = RAW_DIR / tournament_id
    directory.mkdir(parents=True, exist_ok=True)
    participants_path = directory / "participants.json"
    matches_path = directory / "matches.json"
    participants_path.write_text(
        json.dumps(participants, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    matches_path.write_text(
        json.dumps(matches, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return participants_path, matches_path


def stage_and_side(attrs: dict[str, Any]) -> tuple[str, str]:
    if attrs.get("group_id") is not None:
        return "group", "round_robin"

    round_number = attrs.get("round")
    if isinstance(round_number, int):
        if round_number < 0:
            return "knockout", "losers"
        if round_number > 0:
            return "knockout", "winners"
    return "knockout", "unknown"


def validate_match(
    attrs: dict[str, Any],
    p1: str,
    p2: str,
    winner: str | None,
    score: ParsedScore,
) -> list[str]:
    issues: list[str] = []
    if p1 == p2:
        issues.append("Player is matched against themselves")
    if winner is not None and winner not in {p1, p2}:
        issues.append("Winner is not one of the two players")
    p1_score = score.player_1_score
    p2_score = score.player_2_score

    if p1_score is not None and p2_score is not None and winner is not None:
        if winner == p1 and p1_score <= p2_score:
            issues.append("Score conflicts with winner")
        if winner == p2 and p2_score <= p1_score:
            issues.append("Score conflicts with winner")
    if attrs.get("state") == "complete" and winner is None:
        issues.append("Completed match without a winner")
    return issues


def import_payloads(
    tournament_id: str,
    participants_payload: Any,
    matches_payload: Any,
    replace: bool = False,
) -> dict[str, Any]:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    ensure_match_columns(connection)

    tournament = connection.execute(
        "SELECT tournament_id FROM tournaments WHERE tournament_id = ?",
        (tournament_id,),
    ).fetchone()
    if tournament is None:
        connection.close()
        raise ValueError(f"Unknown internal tournament ID: {tournament_id}")

    alias_map = load_alias_map(connection)
    participant_map: dict[str, str] = {}
    participant_rows: list[tuple[str, str, int | None, int | None]] = []
    unknown_names: list[str] = []

    for item in unwrap_items(participants_payload):
        attrs = attributes(item, "participant")
        challonge_id = str(attrs.get("id", item.get("id", "")))
        raw_name = str(attrs.get("name", "")).strip()
        if not challonge_id or not raw_name:
            continue

        player_id = alias_map.get(normalize_alias(raw_name))
        if player_id is None:
            unknown_names.append(raw_name)
            continue

        # KO bracket participant ID.
        participant_map[challonge_id] = player_id
        # Group stage uses separate IDs; Challonge exposes the mapping here.
        for group_player_id in attrs.get("group_player_ids") or []:
            participant_map[str(group_player_id)] = player_id

        participant_rows.append(
            (tournament_id, player_id, attrs.get("final_rank"), attrs.get("seed"))
        )

    if unknown_names:
        connection.close()
        names = ", ".join(sorted(set(unknown_names), key=str.casefold))
        raise ValueError(
            "Unknown aliases found: " + names + ". "
            "Assign them with add_alias.py first."
        )

    match_rows: list[tuple[Any, ...]] = []
    skipped: list[str] = []
    validation_issues: list[str] = []
    stages = {"group": 0, "knockout": 0}

    for item in unwrap_items(matches_payload):
        attrs = attributes(item, "match")
        challonge_match_id = str(attrs.get("id", item.get("id", "")))
        p1_challonge = attrs.get("player1_id")
        p2_challonge = attrs.get("player2_id")
        winner_challonge = attrs.get("winner_id")

        if not challonge_match_id or p1_challonge is None or p2_challonge is None:
            skipped.append(challonge_match_id or "<no ID>")
            continue

        p1 = participant_map.get(str(p1_challonge))
        p2 = participant_map.get(str(p2_challonge))
        winner = participant_map.get(str(winner_challonge)) if winner_challonge is not None else None
        if p1 is None or p2 is None:
            skipped.append(challonge_match_id)
            continue

        score = parse_score(attrs.get("scores_csv", attrs.get("scores")), winner is not None)
        stage, bracket_side = stage_and_side(attrs)
        stages[stage] += 1
        issues = validate_match(attrs, p1, p2, winner, score)
        validation_issues.extend(f"Match {challonge_match_id}: {issue}" for issue in issues)

        internal_match_id = f"{tournament_id}_challonge_{challonge_match_id}"
        round_number = attrs.get("round")
        round_label = str(round_number) if round_number is not None else None
        match_rows.append(
            (
                internal_match_id,
                tournament_id,
                round_label,
                bracket_side,
                p1,
                p2,
                winner,
                score.player_1_score,
                score.player_2_score,
                int(score.known),
                int(bool(attrs.get("forfeited"))),
                "challonge",
                stage,
                challonge_match_id,
                attrs.get("identifier"),
                str(attrs["group_id"]) if attrs.get("group_id") is not None else None,
                round_number,
                attrs.get("suggested_play_order"),
                attrs.get("completed_at"),
            )
        )

    if skipped:
        connection.close()
        raise ValueError(
            "Matches could not be mapped: " + ", ".join(skipped)
        )
    if validation_issues:
        connection.close()
        raise ValueError("Validation errors:\n- " + "\n- ".join(validation_issues))

    with connection:
        if replace:
            connection.execute("DELETE FROM matches WHERE tournament_id = ?", (tournament_id,))
            connection.execute(
                "DELETE FROM tournament_participants WHERE tournament_id = ?",
                (tournament_id,),
            )

        connection.executemany(
            """
            INSERT OR REPLACE INTO tournament_participants
                (tournament_id, player_id, placement, seed)
            VALUES (?, ?, ?, ?)
            """,
            participant_rows,
        )
        connection.executemany(
            """
            INSERT OR REPLACE INTO matches
                (match_id, tournament_id, round_label, bracket_side,
                 player_1_id, player_2_id, winner_id,
                 player_1_score, player_2_score, score_known,
                 walkover, source, stage, challonge_match_id,
                 challonge_identifier, challonge_group_id, challonge_round,
                 suggested_play_order, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            match_rows,
        )
        connection.execute(
            """
            UPDATE tournaments
            SET bracket_source = 'challonge', match_data_available = 1
            WHERE tournament_id = ?
            """,
            (tournament_id,),
        )

    result = {
        "tournament_id": tournament_id,
        "participants": len(participant_rows),
        "matches": len(match_rows),
        "group_matches": stages["group"],
        "knockout_matches": stages["knockout"],
        "scores_known": sum(row[9] for row in match_rows),
        "scores_unknown": sum(1 - row[9] for row in match_rows),
        "unknown_aliases": 0,
        "skipped": 0,
        "validation_errors": 0,
    }
    connection.close()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Import Challonge tournament")
    parser.add_argument("tournament_id", help="internal ID, e.g. wm_13")
    parser.add_argument("--challonge-id", help="Challonge tournament ID or URL slug")
    parser.add_argument(
        "--from-files", action="store_true", help="read JSON from data/raw/<tournament>/"
    )
    parser.add_argument(
        "--replace", action="store_true", help="replace existing tournament data"
    )
    args = parser.parse_args()

    raw_directory = RAW_DIR / args.tournament_id
    if args.from_files:
        participants_payload = json.loads(
            (raw_directory / "participants.json").read_text(encoding="utf-8")
        )
        matches_payload = json.loads(
            (raw_directory / "matches.json").read_text(encoding="utf-8")
        )
    else:
        if not args.challonge_id:
            parser.error("--challonge-id is required unless --from-files is used")
        participants_payload = fetch_json(args.challonge_id, "participants")
        matches_payload = fetch_json(args.challonge_id, "matches")
        save_raw(args.tournament_id, participants_payload, matches_payload)

    result = import_payloads(
        args.tournament_id,
        participants_payload,
        matches_payload,
        replace=args.replace,
    )

    print(f"\n{args.tournament_id.upper()} imported successfully")
    print(f"Participants:       {result['participants']}")
    print(f"Matches:          {result['matches']}")
    print(f"  Group stage:   {result['group_matches']}")
    print(f"  Knockout stage:       {result['knockout_matches']}")
    print(f"Known scores:   {result['scores_known']}")
    print(f"unknown scores: {result['scores_unknown']}")
    print(f"Unknown aliases:{result['unknown_aliases']:>4}")
    print(f"Errors:           {result['validation_errors']}")


if __name__ == "__main__":
    main()
