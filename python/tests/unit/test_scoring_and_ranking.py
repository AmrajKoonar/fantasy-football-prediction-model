import pytest

from fantasy_football_prediction_model.config import get_settings
from fantasy_football_prediction_model.projections.constraints import (
    apply_constraints,
    enforce_quantile_ordering,
)
from fantasy_football_prediction_model.projections.generate import generate_projections
from fantasy_football_prediction_model.projections.ranking import RankablePlayer, rank_players
from fantasy_football_prediction_model.projections.replacement_value import (
    PlayerPoints,
    compute_replacement_levels,
    vorp,
)
from fantasy_football_prediction_model.projections.scoring import rules_from_preset, score_total


def test_full_ppr_scoring():
    settings = get_settings()
    rules = rules_from_preset(settings.scoring, "ppr")
    total = score_total(
        {
            "receptions": 80,
            "receiving_yards": 1000,
            "receiving_tds": 8,
        },
        rules,
    )
    assert total == pytest.approx(80 + 100 + 48)


def test_half_ppr_differs():
    settings = get_settings()
    ppr = score_total({"receptions": 10}, rules_from_preset(settings.scoring, "ppr"))
    half = score_total({"receptions": 10}, rules_from_preset(settings.scoring, "half_ppr"))
    assert ppr - half == pytest.approx(5)


def test_constraints_ratio():
    stats = apply_constraints({"games": 18, "targets": 10, "receptions": 12, "carries": -1})
    assert stats["games"] == 17
    assert stats["receptions"] == 10
    assert stats["carries"] == 0


def test_quantile_ordering():
    low, median, high = enforce_quantile_ordering(120, 100, 90)
    assert low <= median <= high


def test_vorp_and_ranking():
    settings = get_settings()
    players = [
        PlayerPoints(player_id=f"p{i}", position=pos, points=300 - i * 3)
        for i, pos in enumerate(["QB"] * 15 + ["RB"] * 30 + ["WR"] * 40 + ["TE"] * 15)
    ]
    levels = compute_replacement_levels(players, settings.league)
    assert levels.levels["QB"] > 0
    assert vorp(300, "QB", levels) > 0

    rankable = [
        RankablePlayer(
            player_id=p.player_id,
            position=p.position,
            points=p.points,
            points_per_game=p.points / 16,
            low_points=p.points * 0.8,
            high_points=p.points * 1.2,
        )
        for p in players
    ]
    result = rank_players(rankable, settings.league)
    ranks = [p.overall_rank for p in result.players]
    assert ranks == list(range(1, len(ranks) + 1))


def test_fixture_generation_labelled():
    settings = get_settings()
    bundle = generate_projections(settings, fixture=True, output_count=20)
    assert bundle.data_mode == "fixture"
    assert len(bundle.players) == 20
    assert all(w.code == "fixture_data" for p in bundle.players for w in p.warnings)
