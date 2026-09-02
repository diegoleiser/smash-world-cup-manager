# Smash World Championship Dashboard

The Streamlit dashboard is the UI for the archive, statistics, Tournament
Manager and live forecasts. `dashboard.py` is the entry point; page modules
live in `src/dashboard_pages/`, with tournament, statistics and forecast logic
in their focused packages under `src/`.

## Installation

```bash
python3 -m pip install -r requirements.txt
python3 -m pip install -r requirements-dashboard.txt
```

## Run

```bash
python3 -m streamlit run dashboard.py
```

Streamlit should then open the dashboard automatically in your browser.

The private database is expected at `data/smash_wm.db`. See `README.md` for
initialization, imports, verification and privacy rules.
