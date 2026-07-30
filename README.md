# Smash World Cup Manager

A Streamlit dashboard and SQLite archive for a private Super Smash Bros. tournament series.

The project provides:

- tournament and player statistics
- Elo rankings and rating history
- head-to-head records
- an internal Tournament Manager for Group Stage and Double Elimination
- live Monte Carlo qualification, bracket, and title forecasts
- Challonge tournament imports
- data validation tools

## Tournament Manager and live forecasts

The Tournament Manager supports:

- 3–32 participants, including inactive and newly created players
- one or multiple Round Robin groups
- split entry into Winners and Losers after the Group Stage
- Double Elimination without a Group Stage, with all players in Winners
- bracket sizes from 4 to 32, including Byes
- live Winners, Grand Final, title, and open-Set leverage probabilities
- fixed completed results and automatic recalculation after new results
- Grand Final Reset handling

Players absent from the current model artifact receive a clearly labelled
neutral runtime prior. This does not modify the trained artifact.

The separate Monte Carlo page remains a lightweight planning and test tool.
The Tournament Manager is the production surface for forecasts during a WC.

Current forecast limitations:

- a real two-player Bracket Set stored as `cancelled` is not simulated
- multi-group lock labels remain conservative while any Group Set is open
- the provisional forecast UI may be redesigned independently of the model

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

To test the configured credentials without importing data, set
`CHALLONGE_TEST_TOURNAMENT_ID` in `.env` and run:

```bash
python src/check_challonge_connection.py
```

Manual corrections can be stored in `data/overrides/`.

## Verification

```bash
python src/verify_all.py
python src/verify_import.py wc_01
```

## Private data

The database, seed file, Challonge exports, overrides, registry, and `.env` file are excluded through `.gitignore` and remain local.
