from fantasy_football_prediction_model.config import get_settings
from fantasy_football_prediction_model.projections.generate import generate_projections
from fantasy_football_prediction_model.projections.ranking_inclusions import (
    RankingInclusion,
    select_published_players,
)


def _inclusion(player_id: str, player_name: str) -> RankingInclusion:
    return RankingInclusion(
        player_id=player_id,
        player_name=player_name,
        reason="Coverage audit",
        source_note="Reference rankings",
        date_entered="2026-07-29",
        reference_rank=25,
    )


def test_forced_inclusion_keeps_full_pool_model_rank_in_context():
    bundle = generate_projections(get_settings(), fixture=True, output_count=4)
    forced = bundle.players[3]

    published, warnings = select_published_players(
        bundle.players,
        [_inclusion(forced.player_id, forced.name)],
        limit=2,
    )

    assert [player.player_id for player in published] == [
        bundle.players[0].player_id,
        bundle.players[1].player_id,
        forced.player_id,
    ]
    assert forced.fantasy.overall_rank == 3
    assert forced.context["modelOverallRank"] == 4.0
    assert forced.warnings[-1].code == "ranking_coverage_inclusion"
    assert "model top-2" in forced.warnings[-1].message
    assert "Full-pool model rank: 4" in forced.warnings[-1].message
    assert warnings == [
        "Published 1 manual ranking coverage inclusion(s) outside "
        "the model top-2; full-pool model ranks are preserved in player context."
    ]


def test_missing_inclusion_is_reported():
    bundle = generate_projections(get_settings(), fixture=True, output_count=2)

    published, warnings = select_published_players(
        bundle.players,
        [_inclusion("not-in-pool", "Missing Player")],
        limit=2,
    )

    assert published == bundle.players
    assert warnings == ["Ranking inclusion missing from candidate pool: Missing Player."]
