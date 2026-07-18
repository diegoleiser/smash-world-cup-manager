# Smash World Cup Manager

A Streamlit dashboard and SQLite archive for a private Super Smash Bros. tournament series.

The project provides:

- tournament and player statistics
- Elo rankings and rating history
- head-to-head records
- Challonge tournament imports
- data validation tools

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install -r requirements-dashboard.txt
```

## Run the dashboard

```bash
python -m streamlit run dashboard.py
```

The dashboard reads its data from:

```text
data/smash_wm.db
```

## Initialize a database

Create a private seed file from the included example:

```bash
cp examples/seed.example.json data/private_seed.json
python src/init_db.py
```

To replace an existing database:

```bash
python src/init_db.py --replace
```

## Challonge imports

Create a local `.env` file when Challonge access is needed:

```bash
cp .env.example .env
```

Then import a tournament:

```bash
python src/challonge_import.py wc_01 --challonge-id YOUR_TOURNAMENT_SLUG --replace
```

Manual corrections can be stored in `data/overrides/`.

## Verification

```bash
python src/verify_all.py
python src/verify_import.py wc_01
```

## Private data

The database, seed file, Challonge exports, overrides, registry, and `.env` file are excluded through `.gitignore` and remain local.
