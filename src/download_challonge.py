from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
API_BASE = "https://api.challonge.com/v1"


def load_env_file(path: Path) -> None:
    """Load simple KEY=VALUE entries without printing secrets."""
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(
            key.strip(),
            value.strip().strip('"').strip("'"),
        )


def fetch_json(session: requests.Session, path: str, api_key: str) -> Any:
    response = session.get(
        f"{API_BASE}{path}",
        params={"api_key": api_key},
        headers={
            "Accept": "application/json",
            "User-Agent": "curl/8.7.1",
            "Connection": "close",
        },
        timeout=30,
    )

    safe_url = response.url.replace(api_key, "***")
    print(f"GET {safe_url}")
    print(f"HTTP {response.status_code}")

    if not response.ok:
        print(response.text[:1000])
        response.raise_for_status()

    return response.json()


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Archive raw Challonge API v1 data locally"
    )
    parser.add_argument("tournament_id", help="internal ID, e.g. wm_13")
    parser.add_argument("challonge_id", help="Challonge tournament slug")
    args = parser.parse_args()

    load_env_file(ROOT / ".env")
    api_key = os.environ.get("CHALLONGE_API_KEY")
    if not api_key:
        raise SystemExit(
            "CHALLONGE_API_KEY is missing. Check the .env file in the project directory."
        )

    # Important on the user's setup: do not inherit proxy/environment settings.
    session = requests.Session()
    session.trust_env = False

    tournament = fetch_json(
        session,
        f"/tournaments/{args.challonge_id}.json",
        api_key,
    )
    participants = fetch_json(
        session,
        f"/tournaments/{args.challonge_id}/participants.json",
        api_key,
    )
    matches = fetch_json(
        session,
        f"/tournaments/{args.challonge_id}/matches.json",
        api_key,
    )

    output_dir = RAW_DIR / args.tournament_id
    output_dir.mkdir(parents=True, exist_ok=True)

    write_json(output_dir / "tournament.json", tournament)
    write_json(output_dir / "participants.json", participants)
    write_json(output_dir / "matches.json", matches)

    tournament_data = tournament.get("tournament", tournament)
    print("\nArchive completed successfully!")
    print(f"Tournament: {tournament_data.get('name', 'unknown')}")
    print(f"Participants: {len(participants)}")
    print(f"Matches: {len(matches)}")
    print(f"Directory: {output_dir}")


if __name__ == "__main__":
    main()
