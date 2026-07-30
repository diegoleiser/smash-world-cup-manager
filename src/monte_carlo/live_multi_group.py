"""Joint live forecasts for multiple tournament groups."""

from __future__ import annotations

import random
from dataclasses import dataclass

from monte_carlo.group_simulation import SimulationPlayer
from monte_carlo.live_group import (
    LOSERS_LOCKED,
    SIDE_OPEN,
    WINNERS_LOCKED,
    LiveGroupForecast,
    LiveGroupMatch,
    LiveGroupPlayerForecast,
    LiveMatchLeverage,
    _validate_live_group,
    standing_match_dict,
)
from monte_carlo.model import CombinedModel
from monte_carlo.scorelines import simulate_scoreline
from tournament.bracket_constants import ENTRY_SPLIT_BY_GROUP_SEED
from tournament.bracket_seeding import get_bracket_size
from tournament.group_stage_ranking import build_global_group_ranking
from tournament.group_stage_standings import (
    GROUP_MATCH_COMPLETED,
    GROUP_MATCH_FORFEIT,
    GROUP_MATCH_PENDING,
    calculate_group_standings,
)


@dataclass(frozen=True)
class LiveGroupPool:
    group_id: str
    group_name: str
    players: tuple[SimulationPlayer, ...]
    matches: tuple[LiveGroupMatch, ...]


def forecast_live_groups(
    groups: list[LiveGroupPool],
    model: CombinedModel,
    n_simulations: int,
    random_seed: int,
) -> LiveGroupForecast:
    """Simulate all open groups jointly before applying global seeding."""

    if len(groups) < 2:
        raise ValueError("A multi-group forecast requires at least two groups.")
    if n_simulations < 1:
        raise ValueError("n_simulations must be positive.")
    players = [player for group in groups for player in group.players]
    player_ids = [player.player_id for player in players]
    if len(set(player_ids)) != len(player_ids):
        raise ValueError("A player cannot appear in multiple groups.")
    for group in groups:
        _validate_live_group(
            list(group.players),
            list(group.matches),
            model,
        )

    members_by_group = {
        group.group_id: [
            {
                "player_id": player.player_id,
                "player": player.display_name,
                "initial_seed": player.initial_seed,
            }
            for player in group.players
        ]
        for group in groups
    }
    elo_by_player_id = {
        player.player_id: player.initial_elo for player in players
    }
    fixed_by_group = {
        group.group_id: [
            standing_match_dict(match)
            for match in group.matches
            if match.status != GROUP_MATCH_PENDING
        ]
        for group in groups
    }
    pending_matches = [
        (group.group_id, match)
        for group in groups
        for match in group.matches
        if match.status == GROUP_MATCH_PENDING
    ]
    pending_probabilities = [
        model.set_probability(
            match.player_1_id,
            match.player_2_id,
            best_of=3,
        )
        for _, match in pending_matches
    ]

    current_groups = []
    current_by_player_id: dict[str, dict[str, object]] = {}
    for group in groups:
        calculation = calculate_group_standings(
            members_by_group[group.group_id],
            [standing_match_dict(match) for match in group.matches],
            elo_by_player_id,
        )
        current_groups.append(
            {
                "group_id": group.group_id,
                "group_name": group.group_name,
                **calculation,
            }
        )
        current_by_player_id.update(
            {
                str(row["player_id"]): row
                for row in calculation["standings"]
            }
        )
    current_global = build_global_group_ranking(
        current_groups,
        ENTRY_SPLIT_BY_GROUP_SEED,
    )

    participant_count = len(players)
    get_bracket_size(participant_count)
    final_win_totals = {player_id: 0 for player_id in player_ids}
    global_seed_counts = {
        player_id: {
            seed: 0 for seed in range(1, participant_count + 1)
        }
        for player_id in player_ids
    }
    winners_counts = {player_id: 0 for player_id in player_ids}
    outcome_counts = [
        {True: 0, False: 0} for _ in pending_matches
    ]
    qualified_by_outcome = [
        {
            True: {
                match.player_1_id: 0,
                match.player_2_id: 0,
            },
            False: {
                match.player_1_id: 0,
                match.player_2_id: 0,
            },
        }
        for _, match in pending_matches
    ]
    rng = random.Random(random_seed)
    for _ in range(n_simulations):
        simulated_by_group = {
            group_id: list(matches)
            for group_id, matches in fixed_by_group.items()
        }
        simulated_outcomes: list[bool] = []
        for (
            (group_id, match),
            probability,
        ) in zip(
            pending_matches,
            pending_probabilities,
            strict=True,
        ):
            normal, decider = model.game_probabilities(
                match.player_1_id,
                match.player_2_id,
            )
            player_1_won = rng.random() < probability
            simulated_outcomes.append(player_1_won)
            score = simulate_scoreline(
                player_a_won=player_1_won,
                normal_game_probability=normal,
                decider_game_probability=decider,
                best_of=3,
                rng=rng,
            )
            simulated_by_group[group_id].append(
                {
                    "player_1_id": match.player_1_id,
                    "player_2_id": match.player_2_id,
                    "status": GROUP_MATCH_COMPLETED,
                    "winner_id": (
                        match.player_1_id
                        if player_1_won
                        else match.player_2_id
                    ),
                    "player_1_score": score.player_a_score,
                    "player_2_score": score.player_b_score,
                }
            )

        simulated_groups = []
        for group in groups:
            calculation = calculate_group_standings(
                members_by_group[group.group_id],
                simulated_by_group[group.group_id],
                elo_by_player_id,
            )
            simulated_groups.append(
                {
                    "group_id": group.group_id,
                    "group_name": group.group_name,
                    **calculation,
                }
            )
            for row in calculation["standings"]:
                final_win_totals[str(row["player_id"])] += int(
                    row["sets_won"]
                )
        global_ranking = build_global_group_ranking(
            simulated_groups,
            ENTRY_SPLIT_BY_GROUP_SEED,
        )
        qualified_player_ids = {
            str(row["player_id"])
            for row in global_ranking["ranking"]
            if str(row["starts_in"]) == "winners"
        }
        for row in global_ranking["ranking"]:
            player_id = str(row["player_id"])
            global_seed_counts[player_id][int(row["global_seed"])] += 1
            if player_id in qualified_player_ids:
                winners_counts[player_id] += 1
        for index, ((_, match), player_1_won) in enumerate(
            zip(pending_matches, simulated_outcomes, strict=True)
        ):
            outcome_counts[index][player_1_won] += 1
            for player_id in (match.player_1_id, match.player_2_id):
                if player_id in qualified_player_ids:
                    qualified_by_outcome[index][player_1_won][
                        player_id
                    ] += 1

    denominator = float(n_simulations)
    if pending_matches:
        statuses = {player_id: SIDE_OPEN for player_id in player_ids}
    else:
        statuses = {
            player_id: (
                WINNERS_LOCKED
                if winners_counts[player_id] == n_simulations
                else LOSERS_LOCKED
            )
            for player_id in player_ids
        }
    forecasts = tuple(
        LiveGroupPlayerForecast(
            player_id=player.player_id,
            display_name=player.display_name,
            current_sets_won=int(
                current_by_player_id[player.player_id]["sets_won"]
            ),
            current_sets_lost=int(
                current_by_player_id[player.player_id]["sets_lost"]
            ),
            expected_final_sets_won=(
                final_win_totals[player.player_id] / denominator
            ),
            group_seed_probabilities={
                seed: count / denominator
                for seed, count in global_seed_counts[
                    player.player_id
                ].items()
            },
            winners_probability=(
                winners_counts[player.player_id] / denominator
            ),
            winners_status=statuses[player.player_id],
        )
        for player in sorted(players, key=lambda item: item.initial_seed)
    )
    leverage = tuple(
        LiveMatchLeverage(
            player_1_id=match.player_1_id,
            player_2_id=match.player_2_id,
            player_1_set_win_probability=pending_probabilities[index],
            player_1_winners_if_win=(
                qualified_by_outcome[index][True][match.player_1_id]
                / outcome_counts[index][True]
                if outcome_counts[index][True]
                else 0.0
            ),
            player_1_winners_if_loss=(
                qualified_by_outcome[index][False][match.player_1_id]
                / outcome_counts[index][False]
                if outcome_counts[index][False]
                else 0.0
            ),
            player_2_winners_if_win=(
                qualified_by_outcome[index][False][match.player_2_id]
                / outcome_counts[index][False]
                if outcome_counts[index][False]
                else 0.0
            ),
            player_2_winners_if_loss=(
                qualified_by_outcome[index][True][match.player_2_id]
                / outcome_counts[index][True]
                if outcome_counts[index][True]
                else 0.0
            ),
        )
        for index, (_, match) in enumerate(pending_matches)
    )
    return LiveGroupForecast(
        players=forecasts,
        match_leverage=leverage,
        current_standings=tuple(current_global["ranking"]),
        completed_sets=sum(
            match.status
            in {GROUP_MATCH_COMPLETED, GROUP_MATCH_FORFEIT}
            for group in groups
            for match in group.matches
        ),
        pending_sets=len(pending_matches),
        simulation_count=n_simulations,
        random_seed=random_seed,
        model_version=model.config.model_version,
        training_cutoff=model.config.training_cutoff,
        probability_policy=(
            "Completed results fixed; remaining Group Sets use frozen "
            "pre-tournament strengths; global production seeding applied."
        ),
    )
