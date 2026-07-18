from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "smash_wm.db"


def print_table(headers: list[str], rows: list[tuple[object, ...]]) -> None:
    if not rows:
        print("(no data)")
        return
    widths = [len(h) for h in headers]
    for row in rows:
        for i, value in enumerate(row):
            widths[i] = max(widths[i], len("" if value is None else str(value)))
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*headers))
    print(fmt.format(*("-" * w for w in widths)))
    for row in rows:
        print(fmt.format(*("[2mNULL[0m" if v is None else str(v) for v in row)))


def verify(db_path: Path, tournament_id: str) -> int:
    if not db_path.exists():
        print(f"Database not found: {db_path}")
        return 1

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        tournament = conn.execute(
            """
            SELECT t.tournament_id, t.tournament_number, t.tournament_date,
                   p.display_name AS winner, t.bracket_source,
                   t.match_data_available
            FROM tournaments t
            JOIN players p ON p.player_id = t.winner_id
            WHERE t.tournament_id = ?
            """,
            (tournament_id,),
        ).fetchone()

        if tournament is None:
            print(f"Tournament not found: {tournament_id}")
            return 1

        print(f"\nVerification report for {tournament_id.upper()}")
        print("=" * 44)
        print(f"Date:            {tournament['tournament_date']}")
        print(f"Winner:           {tournament['winner']}")
        print(f"Source:           {tournament['bracket_source']}")
        print(f"Match data:       {'yes' if tournament['match_data_available'] else 'no'}")

        participant_rows = conn.execute(
            """
            SELECT tp.placement, p.display_name, tp.seed
            FROM tournament_participants tp
            JOIN players p ON p.player_id = tp.player_id
            WHERE tp.tournament_id = ?
            ORDER BY tp.placement, tp.seed, p.display_name
            """,
            (tournament_id,),
        ).fetchall()

        print("\nParticipants and placements")
        print_table(
            ["Placement", "Players", "Seed"],
            [(r["placement"], r["display_name"], r["seed"]) for r in participant_rows],
        )

        stage_rows = conn.execute(
            """
            SELECT COALESCE(stage, 'unknown') AS stage,
                   COUNT(*) AS matches,
                   SUM(score_known) AS scores_known
            FROM matches
            WHERE tournament_id = ?
            GROUP BY stage
            ORDER BY CASE stage WHEN 'group' THEN 1 WHEN 'knockout' THEN 2 ELSE 3 END
            """,
            (tournament_id,),
        ).fetchall()

        print("\nMatches by stage")
        print_table(
            ["Stage", "Matches", "Known scores"],
            [(r["stage"], r["matches"], r["scores_known"]) for r in stage_rows],
        )

        match_rows = conn.execute(
            """
            SELECT m.stage, m.challonge_identifier,
                   p1.display_name AS player_1,
                   p2.display_name AS player_2,
                   m.player_1_score, m.player_2_score,
                   w.display_name AS winner,
                   m.bracket_side,
                   m.challonge_round
            FROM matches m
            JOIN players p1 ON p1.player_id = m.player_1_id
            JOIN players p2 ON p2.player_id = m.player_2_id
            LEFT JOIN players w ON w.player_id = m.winner_id
            WHERE m.tournament_id = ?
            ORDER BY
              CASE m.stage WHEN 'group' THEN 1 WHEN 'knockout' THEN 2 ELSE 3 END,
              COALESCE(m.suggested_play_order, 9999),
              m.challonge_match_id
            """,
            (tournament_id,),
        ).fetchall()

        print("\nAll imported matches")
        print_table(
            ["Stage", "ID", "Player 1", "Player 2", "Score", "Winner", "Bracket", "Round"],
            [
                (
                    r["stage"], r["challonge_identifier"], r["player_1"], r["player_2"],
                    f"{r['player_1_score']}-{r['player_2_score']}" if r["player_1_score"] is not None and r["player_2_score"] is not None else "?",
                    r["winner"], r["bracket_side"], r["challonge_round"],
                )
                for r in match_rows
            ],
        )

        issues: list[str] = []
        if len(participant_rows) == 0:
            issues.append("no participants imported")
        if len(match_rows) == 0:
            issues.append("no matches imported")

        invalid_winners = conn.execute(
            """
            SELECT COUNT(*)
            FROM matches
            WHERE tournament_id = ?
              AND winner_id IS NOT NULL
              AND winner_id NOT IN (player_1_id, player_2_id)
            """,
            (tournament_id,),
        ).fetchone()[0]
        if invalid_winners:
            issues.append(f"{invalid_winners} matches with an invalid winner")

        bad_scores = conn.execute(
            """
            SELECT COUNT(*)
            FROM matches
            WHERE tournament_id = ? AND score_known = 1 AND (
                player_1_score IS NULL OR player_2_score IS NULL OR
                (winner_id = player_1_id AND player_1_score <= player_2_score) OR
                (winner_id = player_2_id AND player_2_score <= player_1_score)
              )
            """,
            (tournament_id,),
        ).fetchone()[0]
        if bad_scores:
            issues.append(f"{bad_scores} matches with a conflicting score")

        print("\nValidierung")
        if issues:
            for issue in issues:
                print(f"ERROR: {issue}")
            return 2

        print(f"OK: {len(participant_rows)} participants and {len(match_rows)} matches are consistent.")
        return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Verifies an imported World Championship dataset.")
    parser.add_argument("tournament_id", nargs="?", default="wm_13")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()
    raise SystemExit(verify(args.db, args.tournament_id.lower()))


if __name__ == "__main__":
    main()
