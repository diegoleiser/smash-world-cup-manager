import os
import sys

import requests
from dotenv import load_dotenv


load_dotenv()

API_KEY = os.getenv("CHALLONGE_API_KEY")
TOURNAMENT_ID = os.getenv("CHALLONGE_TEST_TOURNAMENT_ID")
BASE_URL = "https://api.challonge.com/v1"


def get_json(endpoint: str):
    session = requests.Session()
    session.trust_env = False
    response = session.get(
        f"{BASE_URL}{endpoint}",
        params={"api_key": API_KEY},
        headers={
            "Accept": "application/json",
            "User-Agent": "smash-world-cup-manager/1.0",
            "Connection": "close",
        },
        timeout=30,
    )
    safe_url = response.url.replace(API_KEY, "***") if API_KEY else response.url
    print(f"URL: {safe_url}")
    print(f"{endpoint}: HTTP {response.status_code}")
    response.raise_for_status()
    return response.json()


def main():
    if not API_KEY:
        sys.exit("No API key found. Check the .env file.")
    if not TOURNAMENT_ID:
        sys.exit("No test tournament configured. Set CHALLONGE_TEST_TOURNAMENT_ID in .env.")

    tournament = get_json(f"/tournaments/{TOURNAMENT_ID}.json")
    participants = get_json(f"/tournaments/{TOURNAMENT_ID}/participants.json")
    matches = get_json(f"/tournaments/{TOURNAMENT_ID}/matches.json")
    tournament_data = tournament.get("tournament", tournament)
    print("\nConnection successful!")
    print(f"Tournament: {tournament_data.get('name', 'unknown')}")
    print(f"Participants: {len(participants)}")
    print(f"Matches: {len(matches)}")


if __name__ == "__main__":
    main()
