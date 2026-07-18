from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "smash_wm.db"


@dataclass(frozen=True)
class TournamentCheck:
    tournament_id: str
    number: int
    date: str
    winner: str
    match_data_available: bool
    participants: int
    matches: int
    known_scores: int
    unknown_scores: int
    invalid_winners: int
    bad_scores: int
    missing_winners: int
    null_placements: int

    @property
    def errors(self) -> list[str]:
        issues: list[str] = []
        if self.match_data_available and self.participants == 0:
            issues.append("no participants")
        if self.match_data_available and self.matches == 0:
            issues.append("no matches")
        if self.invalid_winners:
            issues.append(f"{self.invalid_winners} invalid winners")
        if self.bad_scores:
            issues.append(f"{self.bad_scores} conflicting scores")
        return issues

    @property
    def warnings(self) -> list[str]:
        warnings: list[str] = []
        if not self.match_data_available:
            warnings.append("no match data")
        if self.missing_winners:
            warnings.append(f"{self.missing_winners} missing winners")
        if self.unknown_scores:
            warnings.append(f"{self.unknown_scores} unknown scores")
        if self.participants and self.null_placements:
            warnings.append(f"{self.null_placements} missing placements")
        return warnings

    @property
    def status(self) -> str:
        if self.errors:
            return "ERROR"
        if self.warnings:
            return "WARNING"
        return "OK"


def print_table(headers: list[str], rows: list[tuple[object, ...]]) -> None:
    if not rows:
        print("(no data)")
        return

    text_rows = [["" if value is None else str(value) for value in row] for row in rows]
    widths = [len(header) for header in headers]
    for row in text_rows:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))

    fmt = "  ".join(f"{{:<{width}}}" for width in widths)
    print(fmt.format(*headers))
    print(fmt.format(*("-" * width for width in widths)))
    for row in text_rows:
        print(fmt.format(*row))


def load_checks(conn: sqlite3.Connection) -> list[TournamentCheck]:
    rows = conn.execute(
        """
        SELECT
            t.tournament_id,
            t.tournament_number,
            t.tournament_date,
            p.display_name AS winner,
            t.match_data_available,
            COUNT(DISTINCT tp.player_id) AS participants,
            COUNT(DISTINCT m.match_id) AS matches,
            COUNT(DISTINCT CASE WHEN m.score_known = 1 THEN m.match_id END) AS known_scores,
            COUNT(DISTINCT CASE WHEN m.match_id IS NOT NULL AND m.score_known = 0 THEN m.match_id END) AS unknown_scores,
            COUNT(DISTINCT CASE
                WHEN m.winner_id IS NOT NULL
                 AND m.winner_id NOT IN (m.player_1_id, m.player_2_id)
                THEN m.match_id END
            ) AS invalid_winners,
            COUNT(DISTINCT CASE
                WHEN m.score_known = 1 AND (
                    m.player_1_score IS NULL OR
                    m.player_2_score IS NULL OR
                    (m.winner_id = m.player_1_id AND m.player_1_score <= m.player_2_score) OR
                    (m.winner_id = m.player_2_id AND m.player_2_score <= m.player_1_score)
                ) THEN m.match_id END
            ) AS bad_scores,
            COUNT(DISTINCT CASE
                WHEN m.match_id IS NOT NULL AND m.winner_id IS NULL
                THEN m.match_id END
            ) AS missing_winners,
            COUNT(DISTINCT CASE
                WHEN tp.player_id IS NOT NULL AND tp.placement IS NULL
                THEN tp.player_id END
            ) AS null_placements
        FROM tournaments t
        JOIN players p ON p.player_id = t.winner_id
        LEFT JOIN tournament_participants tp ON tp.tournament_id = t.tournament_id
        LEFT JOIN matches m ON m.tournament_id = t.tournament_id
        GROUP BY
            t.tournament_id,
            t.tournament_number,
            t.tournament_date,
            p.display_name,
            t.match_data_available
        ORDER BY t.tournament_number
        """
    ).fetchall()

    return [
        TournamentCheck(
            tournament_id=row["tournament_id"],
            number=row["tournament_number"],
            date=row["tournament_date"],
            winner=row["winner"],
            match_data_available=bool(row["match_data_available"]),
            participants=row["participants"],
            matches=row["matches"],
            known_scores=row["known_scores"],
            unknown_scores=row["unknown_scores"],
            invalid_winners=row["invalid_winners"],
            bad_scores=row["bad_scores"],
            missing_winners=row["missing_winners"],
            null_placements=row["null_placements"],
        )
        for row in rows
    ]


def verify_all(db_path: Path) -> int:
    if not db_path.exists():
        print(f"Database not found: {db_path}")
        return 1

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        checks = load_checks(conn)

        if not checks:
            print("No tournaments found in the database.")
            return 1

        print("\nFull verification of the Smash World Championship archive")
        print("=" * 88)

        rows: list[tuple[object, ...]] = []
        for check in checks:
            notes = check.errors + check.warnings
            rows.append(
                (
                    f"WM {check.number:02d}",
                    check.date,
                    check.winner,
                    check.participants,
                    check.matches,
                    check.known_scores,
                    check.status,
                    "; ".join(notes) if notes else "–",
                )
            )

        print_table(
            ["Tournament", "Date", "Winner", "TN", "Matches", "Scores", "Status", "Notes"],
            rows,
        )

        total_players = conn.execute("SELECT COUNT(*) FROM players").fetchone()[0]
        active_players = conn.execute("SELECT COUNT(*) FROM players WHERE active = 1").fetchone()[0]
        total_matches = conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
        known_scores = conn.execute("SELECT COUNT(*) FROM matches WHERE score_known = 1").fetchone()[0]
        imported_tournaments = sum(1 for check in checks if check.matches > 0)
        no_match_data = sum(1 for check in checks if not check.match_data_available)
        errors = sum(len(check.errors) for check in checks)
        warnings = sum(len(check.warnings) for check in checks)

        orphan_participants = conn.execute(
            """
            SELECT COUNT(*)
            FROM tournament_participants tp
            LEFT JOIN tournaments t ON t.tournament_id = tp.tournament_id
            LEFT JOIN players p ON p.player_id = tp.player_id
            WHERE t.tournament_id IS NULL OR p.player_id IS NULL
            """
        ).fetchone()[0]
        orphan_matches = conn.execute(
            """
            SELECT COUNT(*)
            FROM matches m
            LEFT JOIN tournaments t ON t.tournament_id = m.tournament_id
            LEFT JOIN players p1 ON p1.player_id = m.player_1_id
            LEFT JOIN players p2 ON p2.player_id = m.player_2_id
            WHERE t.tournament_id IS NULL
               OR p1.player_id IS NULL
               OR p2.player_id IS NULL
            """
        ).fetchone()[0]

        if orphan_participants:
            errors += 1
        if orphan_matches:
            errors += 1

        print("\nOverall summary")
        print("-" * 44)
        print(f"Tournaments created:       {len(checks)}")
        print(f"Tournaments with matches:    {imported_tournaments}")
        print(f"Tournaments without match data:{no_match_data:>5}")
        print(f"Players:                 {total_players} ({active_players} active)")
        print(f"Matches:                 {total_matches}")
        print(f"Known scores:            {known_scores}")
        print(f"Unknown scores:        {total_matches - known_scores}")
        print(f"Warnings:               {warnings}")
        print(f"Errors:                  {errors}")

        print("\nDatabase integrity")
        if orphan_participants:
            print(f"ERROR: {orphan_participants} orphaned participant records")
        if orphan_matches:
            print(f"ERROR: {orphan_matches} orphaned matches")
        if not orphan_participants and not orphan_matches:
            print("OK: No orphaned participants or matches.")

        print("\nResult")
        if errors:
            print("ERROR: The archive contains inconsistencies.")
            return 2
        if warnings:
            print("OK WITH WARNINGS: The imported data is consistent; documented gaps remain.")
            return 0

        print("OK: The entire archive is consistent.")
        return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Verifies all tournaments in the Smash World Championship archive.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()
    raise SystemExit(verify_all(args.db))


if __name__ == "__main__":
    main()
