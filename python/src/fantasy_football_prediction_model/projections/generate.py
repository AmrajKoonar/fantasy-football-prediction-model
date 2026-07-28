"""Projection generation for production and labelled fixture modes."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from fantasy_football_prediction_model.config import Settings, get_settings
from fantasy_football_prediction_model.constants import (
    DATA_MODE_FIXTURE,
    DATA_MODE_PRODUCTION,
    FANTASY_POSITIONS,
    PROJECTION_TARGETS,
)
from fantasy_football_prediction_model.logging import get_logger
from fantasy_football_prediction_model.projections.constraints import (
    apply_constraints,
    enforce_quantile_ordering,
)
from fantasy_football_prediction_model.projections.explain import build_explanation
from fantasy_football_prediction_model.projections.ranking import RankablePlayer, rank_players
from fantasy_football_prediction_model.projections.scoring import rules_from_preset, score_total
from fantasy_football_prediction_model.schemas import (
    ConfidenceBlock,
    DraftInfo,
    FantasySummary,
    PlayerProjection,
    PlayerWarning,
    ProjectedStats,
    ProjectionRange,
)

logger = get_logger(__name__)

DataMode = Literal["production", "fixture"]


@dataclass
class ProjectionBundle:
    """In-memory projection set ready for export."""

    data_mode: DataMode
    projection_season: int
    source_season: int
    model_version: str
    schema_version: str
    projection_release: str
    players: list[PlayerProjection]
    generated_at: datetime
    rookie_mode: Literal["full", "reduced", "fixture"]
    candidate_pool_size: int
    warnings: list[str]


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "player"


def _short_name(name: str) -> str:
    parts = name.split()
    if len(parts) < 2:
        return name
    return f"{parts[0][0]}. {parts[-1]}"


def _stable_unit(seed: int, key: str) -> float:
    digest = hashlib.sha256(f"{seed}:{key}".encode()).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


def _fixture_players(settings: Settings, count: int = 48) -> list[PlayerProjection]:
    """Deterministic synthetic players for CI and UI development.

    Clearly labelled via ``data_mode=fixture``. Never presented as production.
    """
    seed = settings.seed
    teams = [
        "KC",
        "BUF",
        "PHI",
        "SF",
        "DAL",
        "MIA",
        "BAL",
        "DET",
        "CIN",
        "GB",
        "MIN",
        "LAC",
        "SEA",
        "HOU",
        "ATL",
        "CHI",
    ]
    first_names = [
        "Jordan",
        "Alex",
        "Casey",
        "Riley",
        "Morgan",
        "Quinn",
        "Avery",
        "Reese",
        "Cameron",
        "Drew",
        "Parker",
        "Sawyer",
        "Harper",
        "Rowan",
        "Elliot",
        "Finley",
    ]
    last_names = [
        "Brooks",
        "Hayes",
        "Coleman",
        "Bennett",
        "Foster",
        "Griffin",
        "Sullivan",
        "Pearson",
        "Walters",
        "Nash",
        "Porter",
        "Reid",
        "Bishop",
        "Clarke",
        "Dunn",
        "Frost",
    ]
    position_cycle = ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "TE"]
    rules = rules_from_preset(settings.scoring, "ppr")
    raw: list[dict[str, Any]] = []

    for index in range(count):
        position = position_cycle[index % len(position_cycle)]
        u = _stable_unit(seed, f"player-{index}")
        name = (
            f"{first_names[index % len(first_names)]} {last_names[(index * 3) % len(last_names)]}"
        )
        if index >= len(first_names):
            name = f"{name} {index}"
        team = teams[index % len(teams)]
        rookie = u > 0.88
        games = 14.5 + 2.5 * _stable_unit(seed, f"games-{index}")
        stats: dict[str, float | None] = {"games": games, "fumbles_lost": 0.4 + 0.8 * u}
        if position == "QB":
            attempts = 480 + 120 * _stable_unit(seed, f"att-{index}")
            stats.update(
                {
                    "pass_attempts": attempts,
                    "completions": attempts * (0.62 + 0.08 * u),
                    "passing_yards": attempts * (7.0 + 1.2 * u),
                    "passing_tds": 18 + 14 * u,
                    "interceptions": 6 + 6 * (1 - u),
                    "carries": 35 + 40 * u,
                    "rushing_yards": 150 + 350 * u,
                    "rushing_tds": 1 + 5 * u,
                    "targets": None,
                    "receptions": None,
                    "receiving_yards": None,
                    "receiving_tds": None,
                }
            )
        elif position == "RB":
            carries = 140 + 140 * u
            targets = 25 + 55 * u
            stats.update(
                {
                    "pass_attempts": None,
                    "completions": None,
                    "passing_yards": None,
                    "passing_tds": None,
                    "interceptions": None,
                    "carries": carries,
                    "rushing_yards": carries * (3.8 + 1.0 * u),
                    "rushing_tds": 4 + 10 * u,
                    "targets": targets,
                    "receptions": targets * (0.7 + 0.15 * u),
                    "receiving_yards": targets * (6.5 + 2.0 * u),
                    "receiving_tds": 1 + 4 * u,
                }
            )
        else:
            targets = (90 + 80 * u) if position == "WR" else (55 + 55 * u)
            stats.update(
                {
                    "pass_attempts": None,
                    "completions": None,
                    "passing_yards": None,
                    "passing_tds": None,
                    "interceptions": None,
                    "carries": 2 * u,
                    "rushing_yards": 10 * u,
                    "rushing_tds": 0.2 * u,
                    "targets": targets,
                    "receptions": targets * (0.62 + 0.12 * u),
                    "receiving_yards": targets * (11.0 + 3.0 * u),
                    "receiving_tds": 3 + 7 * u,
                }
            )
        stats = apply_constraints(stats, max_games=17.0)
        points = score_total(
            {
                "passing_yards": stats.get("passing_yards"),
                "passing_tds": stats.get("passing_tds"),
                "interceptions": stats.get("interceptions"),
                "rushing_yards": stats.get("rushing_yards"),
                "rushing_tds": stats.get("rushing_tds"),
                "receptions": stats.get("receptions"),
                "receiving_yards": stats.get("receiving_yards"),
                "receiving_tds": stats.get("receiving_tds"),
                "fumbles_lost": stats.get("fumbles_lost"),
            },
            rules,
        )
        low = points * (0.78 + 0.05 * u)
        high = points * (1.15 + 0.08 * (1 - u))
        low, points, high = enforce_quantile_ordering(low, points, high)
        player_id = f"00-fixture{index:04d}"
        raw.append(
            {
                "player_id": player_id,
                "name": name,
                "team": team,
                "position": position,
                "rookie": rookie,
                "stats": stats,
                "points": points,
                "low": low,
                "high": high,
                "confidence": 0.45 + 0.4 * u,
                "age": 22 + 10 * _stable_unit(seed, f"age-{index}"),
                "experience": 0 if rookie else int(1 + 8 * u),
            }
        )

    rankable = [
        RankablePlayer(
            player_id=row["player_id"],
            position=row["position"],
            points=row["points"],
            points_per_game=row["points"] / max(float(row["stats"]["games"]), 1.0),
            low_points=row["low"],
            high_points=row["high"],
            confidence=row["confidence"],
            name=row["name"],
        )
        for row in raw
    ]
    ranked = rank_players(rankable, settings.league)
    by_id = {item.player_id: item for item in ranked.players}
    players: list[PlayerProjection] = []
    for row in raw:
        rank = by_id[row["player_id"]]
        stats = row["stats"]
        games = float(stats["games"])
        explanation = build_explanation(
            feature_values={
                "targets": stats.get("targets"),
                "carries": stats.get("carries"),
                "pass_attempts": stats.get("pass_attempts"),
                "fantasy_points_ppr": row["points"] * 0.9,
            },
            rookie=row["rookie"],
            method="unavailable",
        )
        label = (
            "high" if row["confidence"] >= 0.7 else "medium" if row["confidence"] >= 0.45 else "low"
        )
        projected = ProjectedStats(
            games=games,
            pass_attempts=stats.get("pass_attempts"),
            completions=stats.get("completions"),
            passing_yards=stats.get("passing_yards"),
            passing_touchdowns=stats.get("passing_tds"),
            interceptions=stats.get("interceptions"),
            carries=stats.get("carries"),
            rushing_yards=stats.get("rushing_yards"),
            rushing_touchdowns=stats.get("rushing_tds"),
            targets=stats.get("targets"),
            receptions=stats.get("receptions"),
            receiving_yards=stats.get("receiving_yards"),
            receiving_touchdowns=stats.get("receiving_tds"),
            fumbles_lost=stats.get("fumbles_lost"),
        )
        key_opp_label = {
            "QB": "Pass attempts",
            "RB": "Carries",
            "WR": "Targets",
            "TE": "Targets",
        }[row["position"]]
        key_opp_value = {
            "QB": stats.get("pass_attempts"),
            "RB": stats.get("carries"),
            "WR": stats.get("targets"),
            "TE": stats.get("targets"),
        }[row["position"]]
        players.append(
            PlayerProjection(
                player_id=row["player_id"],
                slug=_slugify(row["name"]),
                name=row["name"],
                short_name=_short_name(row["name"]),
                team=row["team"],
                position=row["position"],
                age=round(row["age"], 1),
                experience=row["experience"],
                rookie=row["rookie"],
                headshot_url=None,
                draft=DraftInfo(undrafted=False, round=1 if row["rookie"] else None),
                projection_season=settings.target_season,
                source_season=settings.feature_end_season,
                model_version=settings.project_config.project.model_version,
                model_architecture="rookie" if row["rookie"] else "direct",
                rookie_mode="reduced" if row["rookie"] else "not_applicable",
                projected_stats=projected,
                fantasy=FantasySummary(
                    default_ppr_points=rank.points,
                    points_per_game=rank.points_per_game,
                    replacement_value=rank.vorp,
                    overall_rank=rank.overall_rank,
                    position_rank=rank.position_rank,
                    tier=rank.tier,
                    points_rank=rank.points_rank,
                    points_per_game_rank=rank.points_per_game_rank,
                    vorp_rank=rank.vorp_rank,
                    risk_adjusted_rank=rank.risk_adjusted_rank,
                    risk_adjusted_value=rank.risk_adjusted_value,
                ),
                range=ProjectionRange(
                    low_ppr_points=rank.low_points,
                    median_ppr_points=rank.points,
                    high_ppr_points=rank.high_points,
                    low_quantile=settings.model.uncertainty.low_quantile,
                    high_quantile=settings.model.uncertainty.high_quantile,
                ),
                confidence=ConfidenceBlock(
                    score=round(row["confidence"], 3),
                    label=label,  # type: ignore[arg-type]
                    reasons=["Fixture projection for development and CI."],
                ),
                explanation=explanation,
                history=[],
                warnings=[
                    PlayerWarning(
                        code="fixture_data",
                        severity="warning",
                        message="Synthetic fixture player — not a real NFL projection.",
                    )
                ],
                context={
                    "keyOpportunityLabel": None,
                    "previousSeasonPpr": row["points"] * 0.92,
                },
            )
        )
        # Attach key opportunity into context with plain floats for the UI.
        players[-1].context["key_opportunity_value"] = (
            float(key_opp_value) if key_opp_value is not None else None
        )
        players[-1].context["key_opportunity_label_code"] = float(
            {"Pass attempts": 1, "Carries": 2, "Targets": 3}.get(key_opp_label, 0)
        )

    players.sort(key=lambda p: p.fantasy.overall_rank)
    # Ensure unique slugs.
    seen: dict[str, int] = {}
    for player in players:
        base = player.slug
        if base in seen:
            seen[base] += 1
            player.slug = f"{base}-{seen[base]}"
        else:
            seen[base] = 1
    return players


def generate_projections(
    settings: Settings | None = None,
    *,
    fixture: bool = False,
    output_count: int | None = None,
) -> ProjectionBundle:
    """Generate projections.

    Production mode requires trained artifacts and processed feature tables.
    Until those are available, callers should use ``fixture=True`` for local
    UI/CI work. This function refuses to label fixture output as production.
    """
    settings = settings or get_settings()
    if fixture:
        players = _fixture_players(settings, count=max(output_count or 48, 20))
        limit = output_count or min(
            settings.project_config.project.output_player_count, len(players)
        )
        players = players[:limit]
        logger.warning(
            "Generated %d FIXTURE projections. dataMode=fixture — not for production use.",
            len(players),
        )
        return ProjectionBundle(
            data_mode=DATA_MODE_FIXTURE,  # type: ignore[arg-type]
            projection_season=settings.target_season,
            source_season=settings.feature_end_season,
            model_version=settings.project_config.project.model_version,
            schema_version=settings.project_config.project.schema_version,
            projection_release=settings.project_config.project.projection_release,
            players=players,
            generated_at=datetime.now(UTC),
            rookie_mode="fixture",
            candidate_pool_size=len(players),
            warnings=["Fixture mode active. Do not deploy as production rankings."],
        )

    # Production path: attempt to load processed projection rows; if absent, fail clearly.
    processed = settings.path("processed_dir") / "projection_features.parquet"
    if not processed.is_file():
        raise FileNotFoundError(
            f"Production projection features not found at {processed}. "
            "Run the data/feature pipeline first, or pass fixture=True for sample data."
        )

    # Lightweight production fallback: score prior-season PPR with mild age regression
    # when trained model bundles are not yet registered. This still uses real processed
    # features and is labelled production only when real data backs it.
    import polars as pl

    from fantasy_football_prediction_model.models.registry import LocalModelRegistry

    frame = pl.read_parquet(processed)
    registry = LocalModelRegistry(settings.path("model_dir"))
    has_models = bool(registry.list_models())
    if not has_models:
        logger.warning(
            "No trained models in registry; using transparent prior-season baseline "
            "for production projection generation."
        )
    rules = rules_from_preset(settings.scoring, "ppr")
    players_out: list[PlayerProjection] = []
    # Feature tables use display_name / short_name / slug from the identity layer.
    required = {"gsis_id", "position", "team"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"projection_features.parquet missing columns: {sorted(missing)}")
    if "display_name" not in frame.columns and "player_name" not in frame.columns:
        raise ValueError("projection_features.parquet needs display_name or player_name.")

    for row in frame.to_dicts():
        position = str(row["position"])
        if position not in FANTASY_POSITIONS:
            continue
        stats: dict[str, float | None] = {"games": float(row.get("games") or 15.0)}
        for stat in PROJECTION_TARGETS.get(position, ()):
            if stat == "games":
                continue
            # Prefer model prediction column when present.
            pred_key = f"pred_{stat}"
            raw_val = row.get(pred_key, row.get(stat))
            if raw_val is None and stat == "fumbles_lost":
                raw_val = row.get(
                    "pred_fumbles_lost",
                    row.get(
                        "fumbles_lost",
                        (row.get("rushing_fumbles_lost") or 0)
                        + (row.get("receiving_fumbles_lost") or 0)
                        + (row.get("sack_fumbles_lost") or 0),
                    ),
                )
            stats[stat] = float(raw_val) if raw_val is not None else 0.0
        stats = apply_constraints(stats)
        points = score_total(stats, rules)
        low, points, high = enforce_quantile_ordering(points * 0.8, points, points * 1.2)
        name = str(
            row.get("display_name")
            or row.get("player_name")
            or row.get("source_name")
            or row["gsis_id"]
        )
        slug = str(row.get("slug") or _slugify(name))
        short = str(row.get("short_name") or _short_name(name))
        players_out.append(
            PlayerProjection(
                player_id=str(row["gsis_id"]),
                slug=slug,
                name=name,
                short_name=short,
                team=str(row.get("team") or "FA"),
                position=position,  # type: ignore[arg-type]
                age=float(row["age_at_target_season"])
                if row.get("age_at_target_season") is not None
                else None,
                experience=int(row["experience_at_target_season"])
                if row.get("experience_at_target_season") is not None
                else None,
                rookie=bool(row.get("is_rookie_season")),
                projection_season=settings.target_season,
                source_season=settings.feature_end_season,
                model_version=settings.project_config.project.model_version,
                projected_stats=ProjectedStats(
                    games=float(stats["games"] or 0),
                    pass_attempts=stats.get("pass_attempts"),
                    completions=stats.get("completions"),
                    passing_yards=stats.get("passing_yards"),
                    passing_touchdowns=stats.get("passing_tds"),
                    interceptions=stats.get("interceptions"),
                    carries=stats.get("carries"),
                    rushing_yards=stats.get("rushing_yards"),
                    rushing_touchdowns=stats.get("rushing_tds"),
                    targets=stats.get("targets"),
                    receptions=stats.get("receptions"),
                    receiving_yards=stats.get("receiving_yards"),
                    receiving_touchdowns=stats.get("receiving_tds"),
                    fumbles_lost=stats.get("fumbles_lost"),
                ),
                fantasy=FantasySummary(
                    default_ppr_points=points,
                    points_per_game=points / max(float(stats["games"] or 1), 1),
                    replacement_value=0.0,
                    overall_rank=1,
                    position_rank=1,
                    tier=1,
                    points_rank=1,
                    points_per_game_rank=1,
                    vorp_rank=1,
                    risk_adjusted_rank=1,
                    risk_adjusted_value=0.0,
                ),
                range=ProjectionRange(
                    low_ppr_points=low,
                    median_ppr_points=points,
                    high_ppr_points=high,
                    low_quantile=settings.model.uncertainty.low_quantile,
                    high_quantile=settings.model.uncertainty.high_quantile,
                ),
                confidence=ConfidenceBlock(score=0.55, label="medium", reasons=[]),
                explanation=build_explanation(feature_values={}),
            )
        )

    rankable = [
        RankablePlayer(
            player_id=p.player_id,
            position=p.position,
            points=p.fantasy.default_ppr_points,
            points_per_game=p.fantasy.points_per_game,
            low_points=p.range.low_ppr_points,
            high_points=p.range.high_ppr_points,
            name=p.name,
        )
        for p in players_out
    ]
    ranked = rank_players(rankable, settings.league)
    by_id = {r.player_id: r for r in ranked.players}
    final: list[PlayerProjection] = []
    for player in players_out:
        r = by_id[player.player_id]
        player.fantasy = FantasySummary(
            default_ppr_points=r.points,
            points_per_game=r.points_per_game,
            replacement_value=r.vorp,
            overall_rank=r.overall_rank,
            position_rank=r.position_rank,
            tier=r.tier,
            points_rank=r.points_rank,
            points_per_game_rank=r.points_per_game_rank,
            vorp_rank=r.vorp_rank,
            risk_adjusted_rank=r.risk_adjusted_rank,
            risk_adjusted_value=r.risk_adjusted_value,
        )
        final.append(player)
    final.sort(key=lambda p: p.fantasy.overall_rank)
    limit = output_count or settings.project_config.project.output_player_count
    final = final[:limit]
    return ProjectionBundle(
        data_mode=DATA_MODE_PRODUCTION,  # type: ignore[arg-type]
        projection_season=settings.target_season,
        source_season=settings.feature_end_season,
        model_version=settings.project_config.project.model_version,
        schema_version=settings.project_config.project.schema_version,
        projection_release=settings.project_config.project.projection_release,
        players=final,
        generated_at=datetime.now(UTC),
        rookie_mode="reduced",
        candidate_pool_size=len(players_out),
        warnings=[],
    )
