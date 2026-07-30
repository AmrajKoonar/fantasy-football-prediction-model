"""Write validated static JSON into ``web/public/data``."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fantasy_football_prediction_model.config import Settings
from fantasy_football_prediction_model.constants import DATA_MODE_FIXTURE, DATA_MODE_PRODUCTION
from fantasy_football_prediction_model.exports.metadata import build_metadata
from fantasy_football_prediction_model.logging import get_logger
from fantasy_football_prediction_model.projections.generate import ProjectionBundle
from fantasy_football_prediction_model.schemas import (
    DataCoverageFile,
    FeatureImportanceFile,
    ModelPerformanceFile,
    PlayerIndexEntry,
    PlayersFile,
    ProjectionsFile,
    RankingEntry,
    RankingsFile,
)

logger = get_logger(__name__)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, default=str)
            handle.write("\n")
        tmp_path.replace(path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def _key_opportunity(player: Any) -> tuple[str | None, float | None]:
    stats = player.projected_stats
    if player.position == "QB":
        return "Pass attempts", stats.pass_attempts
    if player.position == "RB":
        return "Carries", stats.carries
    return "Targets", stats.targets


def export_web_data(
    bundle: ProjectionBundle,
    settings: Settings,
    *,
    mock_draft_bundle: ProjectionBundle | None = None,
    performance: ModelPerformanceFile | None = None,
    feature_importance: FeatureImportanceFile | None = None,
    coverage: DataCoverageFile | None = None,
    allow_fixture: bool = True,
) -> dict[str, Path]:
    """Validate and write all static JSON files consumed by the Next.js app."""
    if bundle.data_mode == DATA_MODE_FIXTURE and not allow_fixture:
        raise RuntimeError("Refusing to export fixture data while allow_fixture=False.")
    if bundle.data_mode not in {DATA_MODE_PRODUCTION, DATA_MODE_FIXTURE}:
        raise RuntimeError(f"Unknown data mode {bundle.data_mode!r}.")

    web_dir = settings.path("web_data_dir")
    web_dir.mkdir(parents=True, exist_ok=True)

    projections = ProjectionsFile(
        schema_version=bundle.schema_version,
        data_mode=bundle.data_mode,  # type: ignore[arg-type]
        projection_season=bundle.projection_season,
        generated_at=bundle.generated_at,
        players=bundle.players,
    )
    ranking_entries = [
        RankingEntry(
            player_id=player.player_id,
            slug=player.slug,
            name=player.name,
            team=player.team,
            position=player.position,
            overall_rank=player.fantasy.overall_rank,
            position_rank=player.fantasy.position_rank,
            tier=player.fantasy.tier,
            ppr_points=player.fantasy.default_ppr_points,
            points_per_game=player.fantasy.points_per_game,
            vorp=player.fantasy.replacement_value,
            risk_adjusted_value=player.fantasy.risk_adjusted_value,
            confidence_score=player.confidence.score,
            confidence_label=player.confidence.label,
            rookie=player.rookie,
            games=player.projected_stats.games,
            previous_season_ppr_points=(
                float(player.context["previousSeasonPpr"])
                if player.context.get("previousSeasonPpr") is not None
                else None
            ),
            key_opportunity_label=_key_opportunity(player)[0],
            key_opportunity_value=_key_opportunity(player)[1],
        )
        for player in sorted(bundle.players, key=lambda p: p.fantasy.overall_rank)
    ]
    rankings = RankingsFile(
        schema_version=bundle.schema_version,
        data_mode=bundle.data_mode,  # type: ignore[arg-type]
        projection_season=bundle.projection_season,
        generated_at=bundle.generated_at,
        scoring_preset="ppr",
        entries=ranking_entries,
    )
    players_file = PlayersFile(
        schema_version=bundle.schema_version,
        data_mode=bundle.data_mode,  # type: ignore[arg-type]
        generated_at=bundle.generated_at,
        players=[
            PlayerIndexEntry(
                player_id=player.player_id,
                slug=player.slug,
                name=player.name,
                short_name=player.short_name,
                team=player.team,
                position=player.position,
                rookie=player.rookie,
                overall_rank=player.fantasy.overall_rank,
            )
            for player in bundle.players
        ],
    )
    metadata = build_metadata(bundle, settings)

    if performance is None:
        performance = ModelPerformanceFile(
            schema_version=bundle.schema_version,
            data_mode=bundle.data_mode,  # type: ignore[arg-type]
            generated_at=datetime.now(UTC),
            model_version=bundle.model_version,
            backtest_seasons=[],
            known_weaknesses=[
                "Fixture or incomplete backtest: treat metrics as illustrative only."
                if bundle.data_mode == DATA_MODE_FIXTURE
                else "Run `ffpm model backtest` to populate performance metrics."
            ],
        )
    if feature_importance is None:
        feature_importance = FeatureImportanceFile(
            schema_version=bundle.schema_version,
            data_mode=bundle.data_mode,  # type: ignore[arg-type]
            generated_at=datetime.now(UTC),
        )
    if coverage is None:
        coverage = DataCoverageFile(
            schema_version=bundle.schema_version,
            data_mode=bundle.data_mode,  # type: ignore[arg-type]
            generated_at=datetime.now(UTC),
            datasets=[],
        )

    written = {
        "projections": web_dir / "projections.json",
        "rankings": web_dir / "rankings.json",
        "players": web_dir / "players.json",
        "metadata": web_dir / "metadata.json",
        "model_performance": web_dir / "model-performance.json",
        "feature_importance": web_dir / "feature-importance.json",
        "data_coverage": web_dir / "data-coverage.json",
        "mock_draft_player_pool": web_dir / "mock-draft-player-pool.json",
    }
    _atomic_write_json(written["projections"], projections.model_dump(by_alias=True, mode="json"))
    _atomic_write_json(written["rankings"], rankings.model_dump(by_alias=True, mode="json"))
    _atomic_write_json(written["players"], players_file.model_dump(by_alias=True, mode="json"))
    _atomic_write_json(written["metadata"], metadata.model_dump(by_alias=True, mode="json"))
    _atomic_write_json(
        written["model_performance"], performance.model_dump(by_alias=True, mode="json")
    )
    _atomic_write_json(
        written["feature_importance"], feature_importance.model_dump(by_alias=True, mode="json")
    )
    _atomic_write_json(written["data_coverage"], coverage.model_dump(by_alias=True, mode="json"))
    from fantasy_football_prediction_model.exports.mock_draft import build_mock_draft_pool

    _atomic_write_json(
        written["mock_draft_player_pool"],
        build_mock_draft_pool(mock_draft_bundle or bundle, settings),
    )

    # Also mirror under artifacts/projections for downloads.
    art = settings.path("projection_dir")
    art.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(art / "projections.json", projections.model_dump(by_alias=True, mode="json"))
    _atomic_write_json(art / "rankings.json", rankings.model_dump(by_alias=True, mode="json"))
    _atomic_write_json(art / "metadata.json", metadata.model_dump(by_alias=True, mode="json"))

    logger.info(
        "Exported %d players (%s) to %s",
        len(bundle.players),
        bundle.data_mode,
        web_dir,
    )
    return written
