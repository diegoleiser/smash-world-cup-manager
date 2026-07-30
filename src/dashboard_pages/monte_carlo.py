"""Pre-tournament Monte Carlo dashboard page."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from monte_carlo.artifacts import ArtifactError, load_artifact
from monte_carlo.group_simulation import SimulationPlayer
from monte_carlo.simulation import SimulationResult, simulate_pre_tournament


@st.cache_resource
def _load_model_artifact(artifact_path: str):
    return load_artifact(Path(artifact_path))


def _result_frame(result: SimulationResult) -> pd.DataFrame:
    rows = []
    placements = range(1, len(result.players) + 1)
    for player in result.players:
        row: dict[str, Any] = {
            "Player": player.display_name,
            "Expected Group Wins": player.expected_group_wins,
            "P(Winners)": player.winners_probability * 100,
        }
        row.update(
            {
                f"P{placement}": (
                    player.placement_probabilities[placement] * 100
                )
                for placement in placements
            }
        )
        row["P(GF)"] = player.grand_final_probability * 100
        row["P(Title)"] = player.title_probability * 100
        rows.append(row)
    return pd.DataFrame(rows).sort_values(
        "P(Title)",
        ascending=False,
    )


def render_monte_carlo(
    *,
    artifact_path: Path,
    load_players: Callable[[bool], list[dict[str, Any]]],
    load_elo_ranking: Callable[[bool], list[dict[str, Any]]],
) -> None:
    """Render the first production pre-tournament simulation UI."""

    st.title("Monte Carlo")
    st.caption(
        "Pre-tournament forecast using frozen long-term strength, H2H, "
        "decider Clutch, and one persistent Day value per simulated WC."
    )
    try:
        artifact = _load_model_artifact(str(artifact_path))
    except (ArtifactError, FileNotFoundError, ValueError) as exc:
        st.error(f"Model artifact unavailable: {exc}")
        st.info(
            "Train the local model artifact before running a simulation."
        )
        return

    all_players = load_players(True)
    available_players = [
        player
        for player in all_players
        if str(player["player_id"]) in artifact.model.players
    ]
    player_by_id = {
        str(player["player_id"]): player for player in available_players
    }
    elo_rows = load_elo_ranking(True)
    elo_by_player_id = {
        str(row["player_id"]): float(row["elo"])
        for row in elo_rows
    }
    core_player_ids = [
        str(player["player_id"])
        for player in available_players
        if (
            int(player.get("core_player", 0)) == 1
            and int(player.get("active", 0)) == 1
        )
    ]
    default_player_ids = sorted(
        core_player_ids,
        key=lambda player_id: (
            -elo_by_player_id.get(player_id, 1000.0),
            str(player_by_id[player_id]["display_name"]).casefold(),
        ),
    )[:7]
    selected_ids = st.multiselect(
        "Participants",
        options=list(player_by_id),
        default=default_player_ids,
        format_func=lambda player_id: str(
            player_by_id[player_id]["display_name"]
        ) + (
            ""
            if int(player_by_id[player_id].get("active", 0)) == 1
            else " (inactive)"
        ),
        max_selections=min(32, len(player_by_id)),
    )
    participant_count = len(selected_ids)
    if not 3 <= participant_count <= 32:
        st.warning("Select between 3 and 32 participants.")
        return

    seed_frame = pd.DataFrame(
        [
            {
                "Player ID": player_id,
                "Player": str(player_by_id[player_id]["display_name"]),
                "Seed": index,
            }
            for index, player_id in enumerate(selected_ids, start=1)
        ]
    )
    edited_seeds = st.data_editor(
        seed_frame,
        hide_index=True,
        disabled=["Player ID", "Player"],
        column_config={
            "Player ID": None,
            "Seed": st.column_config.NumberColumn(
                min_value=1,
                max_value=participant_count,
                step=1,
                required=True,
            ),
        },
        width="stretch",
        key="monte_carlo_seeds",
    )
    seeds = [int(value) for value in edited_seeds["Seed"]]
    if sorted(seeds) != list(range(1, participant_count + 1)):
        st.error(
            "Use every Seed from 1 through "
            f"{participant_count} exactly once."
        )
        return
    simulation_configuration = tuple(
        sorted(
            (
                str(row["Player ID"]),
                int(row["Seed"]),
            )
            for _, row in edited_seeds.iterrows()
        )
    )

    controls = st.columns(2)
    simulation_count = controls[0].selectbox(
        "Simulations",
        options=[10_000, 50_000, 100_000],
        index=0,
        format_func=lambda value: f"{value:,}".replace(",", "'"),
    )
    random_seed = int(
        controls[1].number_input(
            "Random Seed",
            min_value=0,
            max_value=2_147_483_647,
            value=20260730,
            step=1,
        )
    )
    st.caption(
        f"Model {artifact.metadata.model_version} · "
        f"Training cutoff {artifact.metadata.training_cutoff}"
    )

    if st.button("Run Simulation", type="primary"):
        simulation_players = [
            SimulationPlayer(
                player_id=str(row["Player ID"]),
                display_name=str(row["Player"]),
                initial_seed=int(row["Seed"]),
                initial_elo=elo_by_player_id.get(
                    str(row["Player ID"]),
                    1000.0,
                ),
            )
            for _, row in edited_seeds.iterrows()
        ]
        with st.spinner("Simulating tournament…"):
            st.session_state["monte_carlo_result"] = (
                simulate_pre_tournament(
                    simulation_players,
                    artifact.model,
                    int(simulation_count),
                    random_seed,
                )
            )
            st.session_state["monte_carlo_result_configuration"] = (
                simulation_configuration
            )

    result = st.session_state.get("monte_carlo_result")
    if (
        not isinstance(result, SimulationResult)
        or st.session_state.get("monte_carlo_result_configuration")
        != simulation_configuration
    ):
        return
    frame = _result_frame(result)
    st.subheader("Tournament Forecast")
    percentage_columns = [
        "P(Winners)",
        *(f"P{placement}" for placement in range(1, participant_count + 1)),
        "P(GF)",
        "P(Title)",
    ]
    st.dataframe(
        frame,
        hide_index=True,
        width="stretch",
        column_config={
            column: st.column_config.NumberColumn(format="%.1f%%")
            for column in percentage_columns
        },
    )
    st.caption(
        "Double Elimination can award tied placements; skipped placement "
        "numbers therefore remain at 0%. Neutral-Day matchup probabilities "
        "and tournament predictive probabilities are different concepts."
    )
    st.metric(
        "Grand Final Reset Probability",
        f"{result.reset_probability:.1%}",
    )
    st.download_button(
        "Download CSV",
        data=frame.to_csv(index=False).encode("utf-8"),
        file_name="monte_carlo_forecast.csv",
        mime="text/csv",
    )
    st.caption(
        f"{result.metadata.simulation_count:,} simulations · "
        f"Random Seed {result.metadata.random_seed} · "
        f"Day sigma {result.metadata.sigma_day:.2f}"
    )
