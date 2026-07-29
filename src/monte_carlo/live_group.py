"""Live Group Stage forecasts with completed results fixed."""

from __future__ import annotations

import random
from dataclasses import dataclass

from monte_carlo.group_simulation import SimulationPlayer
from monte_carlo.model import CombinedModel
from monte_carlo.scorelines import simulate_scoreline
from tournament.group_stage_standings import (
    GROUP_MATCH_CANCELLED,
    GROUP_MATCH_COMPLETED,
    GROUP_MATCH_FORFEIT,
    GROUP_MATCH_PENDING,
    VALID_GROUP_MATCH_STATUSES,
    calculate_group_standings,
)


@dataclass(frozen=True)
class LiveGroupMatch:
    player_1_id: str
    player_2_id: str
    status: str
    winner_id: str | None = None
    player_1_score: int | None = None
    player_2_score: int | None = None


@dataclass(frozen=True)
class LiveGroupPlayerForecast:
    player_id: str
    display_name: str
    current_sets_won: int
    current_sets_lost: int
    expected_final_sets_won: float
    group_seed_probabilities: dict[int, float]
    winners_probability: float
    winners_status: str


@dataclass(frozen=True)
class LiveMatchLeverage:
    player_1_id: str
    player_2_id: str
    player_1_set_win_probability: float
    player_1_winners_if_win: float
    player_1_winners_if_loss: float
    player_2_winners_if_win: float
    player_2_winners_if_loss: float


@dataclass(frozen=True)
class LiveGroupForecast:
    players: tuple[LiveGroupPlayerForecast, ...]
    match_leverage: tuple[LiveMatchLeverage, ...]
    current_standings: tuple[dict[str, object], ...]
    completed_sets: int
    pending_sets: int
    simulation_count: int
    random_seed: int
    model_version: str
    training_cutoff: str
    probability_policy: str


WINNERS_LOCKED = "Winners Locked"
SIDE_OPEN = "Side Open"
LOSERS_LOCKED = "Losers Locked"


def _safe_winners_statuses(
    players: list[SimulationPlayer],
    matches: list[LiveGroupMatch],
    current_by_player_id: dict[str, dict[str, object]],
    winners_count: int,
) -> dict[str, str]:
    """
    Derive only mathematically safe locked states from Set-win bounds.

    Equal maximums remain open because a future tiebreak could still decide
    either way. This deliberately prefers ``Side Open`` over a false lock.
    """

    remaining_by_player_id = {player.player_id: 0 for player in players}
    for match in matches:
        if match.status != GROUP_MATCH_PENDING:
            continue
        remaining_by_player_id[match.player_1_id] += 1
        remaining_by_player_id[match.player_2_id] += 1
    minimum_wins = {
        player.player_id: int(
            current_by_player_id[player.player_id]["sets_won"]
        )
        for player in players
    }
    maximum_wins = {
        player_id: minimum_wins[player_id] + remaining
        for player_id, remaining in remaining_by_player_id.items()
    }
    statuses: dict[str, str] = {}
    for player in players:
        player_id = player.player_id
        possible_challengers = sum(
            other_id != player_id
            and maximum_wins[other_id] >= minimum_wins[player_id]
            for other_id in minimum_wins
        )
        guaranteed_ahead = sum(
            other_id != player_id
            and minimum_wins[other_id] > maximum_wins[player_id]
            for other_id in minimum_wins
        )
        if possible_challengers < winners_count:
            statuses[player_id] = WINNERS_LOCKED
        elif guaranteed_ahead >= winners_count:
            statuses[player_id] = LOSERS_LOCKED
        else:
            statuses[player_id] = SIDE_OPEN
    return statuses


def _validate_live_group(
    players: list[SimulationPlayer],
    matches: list[LiveGroupMatch],
    model: CombinedModel,
) -> None:
    if len(players) < 2:
        raise ValueError("A live group requires at least two players.")
    player_ids = [player.player_id for player in players]
    player_id_set = set(player_ids)
    if len(player_id_set) != len(player_ids):
        raise ValueError("Live group players must be unique.")
    missing_from_model = player_id_set - set(model.players)
    if missing_from_model:
        raise KeyError(
            "Players missing from model artifact: "
            + ", ".join(sorted(missing_from_model))
        )
    seen_pairs: set[frozenset[str]] = set()
    for match in matches:
        if match.status not in VALID_GROUP_MATCH_STATUSES:
            raise ValueError(f"Unsupported live group status: {match.status}")
        if (
            match.player_1_id not in player_id_set
            or match.player_2_id not in player_id_set
        ):
            raise ValueError("Live group Set references a non-member.")
        pair = frozenset((match.player_1_id, match.player_2_id))
        if len(pair) != 2 or pair in seen_pairs:
            raise ValueError("Every live group pairing must be unique.")
        seen_pairs.add(pair)
        if match.status in {GROUP_MATCH_COMPLETED, GROUP_MATCH_FORFEIT}:
            if match.winner_id not in pair:
                raise ValueError("A decided Set requires a valid winner.")
        elif match.winner_id is not None:
            raise ValueError("Pending or cancelled Sets cannot have a winner.")
        if match.status == GROUP_MATCH_COMPLETED:
            scores = (match.player_1_score, match.player_2_score)
            if (scores[0] is None) != (scores[1] is None):
                raise ValueError("A completed Set must have both scores or none.")
        elif (
            match.player_1_score is not None
            or match.player_2_score is not None
        ):
            raise ValueError("Only completed Sets may contain scores.")


def _standing_match(match: LiveGroupMatch) -> dict[str, object]:
    return {
        "player_1_id": match.player_1_id,
        "player_2_id": match.player_2_id,
        "status": match.status,
        "winner_id": match.winner_id,
        "player_1_score": match.player_1_score,
        "player_2_score": match.player_2_score,
    }


def forecast_live_group(
    players: list[SimulationPlayer],
    matches: list[LiveGroupMatch],
    model: CombinedModel,
    n_simulations: int,
    random_seed: int,
    *,
    winners_count: int = 4,
) -> LiveGroupForecast:
    """Forecast a live group while freezing all already resolved Sets."""

    _validate_live_group(players, matches, model)
    if n_simulations < 1:
        raise ValueError("n_simulations must be positive.")
    if not 1 <= winners_count < len(players):
        raise ValueError("winners_count must split the group.")

    members = [
        {
            "player_id": player.player_id,
            "player": player.display_name,
            "initial_seed": player.initial_seed,
        }
        for player in players
    ]
    elo_by_player_id = {
        player.player_id: player.initial_elo for player in players
    }
    current = calculate_group_standings(
        members,
        [_standing_match(match) for match in matches],
        elo_by_player_id,
    )
    current_by_player_id = {
        str(row["player_id"]): row for row in current["standings"]
    }
    pending_matches = [
        match for match in matches if match.status == GROUP_MATCH_PENDING
    ]
    fixed_matches = [
        _standing_match(match)
        for match in matches
        if match.status != GROUP_MATCH_PENDING
    ]

    rng = random.Random(random_seed)
    final_win_totals = {player.player_id: 0 for player in players}
    seed_counts = {
        player.player_id: {
            seed: 0 for seed in range(1, len(players) + 1)
        }
        for player in players
    }
    winners_counts = {player.player_id: 0 for player in players}
    pending_probabilities = [
        model.set_probability(
            match.player_1_id,
            match.player_2_id,
            best_of=3,
        )
        for match in pending_matches
    ]
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
        for match in pending_matches
    ]

    for _ in range(n_simulations):
        simulated_matches = list(fixed_matches)
        simulated_outcomes: list[bool] = []
        for match, probability in zip(
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
            simulated_matches.append(
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
        final_standings = calculate_group_standings(
            members,
            simulated_matches,
            elo_by_player_id,
        )["standings"]
        qualified_player_ids = {
            str(row["player_id"])
            for row in final_standings
            if int(row["placement"]) <= winners_count
        }
        for match_index, (match, player_1_won) in enumerate(
            zip(pending_matches, simulated_outcomes, strict=True)
        ):
            outcome_counts[match_index][player_1_won] += 1
            for player_id in (match.player_1_id, match.player_2_id):
                if player_id in qualified_player_ids:
                    qualified_by_outcome[match_index][player_1_won][
                        player_id
                    ] += 1
        for row in final_standings:
            player_id = str(row["player_id"])
            placement = int(row["placement"])
            final_win_totals[player_id] += int(row["sets_won"])
            seed_counts[player_id][placement] += 1
            if placement <= winners_count:
                winners_counts[player_id] += 1

    denominator = float(n_simulations)
    statuses = _safe_winners_statuses(
        players,
        matches,
        current_by_player_id,
        winners_count,
    )
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
                for seed, count in seed_counts[player.player_id].items()
            },
            winners_probability=(
                winners_counts[player.player_id] / denominator
            ),
            winners_status=statuses[player.player_id],
        )
        for player in sorted(players, key=lambda item: item.initial_seed)
    )
    match_leverage = tuple(
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
        for index, match in enumerate(pending_matches)
    )
    return LiveGroupForecast(
        players=forecasts,
        match_leverage=match_leverage,
        current_standings=tuple(current["standings"]),
        completed_sets=sum(
            match.status in {GROUP_MATCH_COMPLETED, GROUP_MATCH_FORFEIT}
            for match in matches
        ),
        pending_sets=len(pending_matches),
        simulation_count=n_simulations,
        random_seed=random_seed,
        model_version=model.config.model_version,
        training_cutoff=model.config.training_cutoff,
        probability_policy=(
            "Completed results fixed; remaining Sets use frozen "
            "pre-tournament strengths with Day Performance disabled."
        ),
    )
