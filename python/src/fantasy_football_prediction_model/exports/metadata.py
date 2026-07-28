"""Build export metadata and package version stamps."""

from __future__ import annotations

import hashlib
import importlib.metadata
import subprocess
from pathlib import Path

from fantasy_football_prediction_model.config import Settings
from fantasy_football_prediction_model.projections.generate import ProjectionBundle
from fantasy_football_prediction_model.projections.scoring import (
    rules_from_preset,
    rules_to_export_dict,
)
from fantasy_football_prediction_model.schemas import (
    ExportMetadata,
    LeagueDefaultsExport,
    PipelineStageRecord,
    ScoringRuleExport,
    SourceAttribution,
)


def git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None
    return None


def package_versions() -> dict[str, str]:
    names = [
        "fantasy-football-prediction-model",
        "numpy",
        "polars",
        "scikit-learn",
        "pydantic",
        "nflreadpy",
    ]
    out: dict[str, str] = {}
    for name in names:
        try:
            out[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            continue
    return out


def dataset_hash(paths: list[Path]) -> str | None:
    digest = hashlib.sha256()
    found = False
    for path in sorted(paths):
        if not path.is_file():
            continue
        found = True
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest() if found else None


def build_metadata(
    bundle: ProjectionBundle,
    settings: Settings,
    *,
    sources: list[SourceAttribution] | None = None,
    pipeline: list[PipelineStageRecord] | None = None,
    limitations: list[str] | None = None,
    dataset_hash_value: str | None = None,
) -> ExportMetadata:
    rules = rules_from_preset(settings.scoring, "ppr")
    scoring_export = ScoringRuleExport(**rules_to_export_dict(rules))
    league = settings.league.league
    league_export = LeagueDefaultsExport(
        teams=league.teams,
        qb=league.starters.qb,
        rb=league.starters.rb,
        wr=league.starters.wr,
        te=league.starters.te,
        flex=league.starters.flex,
        superflex=league.starters.superflex,
        bench_size=league.bench_size,
        replacement_method=settings.league.replacement.method,
        replacement_ranks=dict(settings.league.replacement.fixed_rank),
        risk_penalty_weight=settings.league.risk.penalty_weight,
    )
    default_limitations = limitations or [
        "Projections are estimates, not guarantees.",
        "Injury reports after 2024 are not automatically ingested.",
        "CollegeFootballData enrichment is optional; reduced rookie mode may apply.",
    ]
    return ExportMetadata(
        schema_version=bundle.schema_version,
        model_version=bundle.model_version,
        projection_release=bundle.projection_release,
        data_mode=bundle.data_mode,  # type: ignore[arg-type]
        projection_season=bundle.projection_season,
        source_season=bundle.source_season,
        data_start_season=settings.data_start_season,
        generated_at=bundle.generated_at,
        git_commit=git_commit(),
        dataset_hash=dataset_hash_value,
        player_count=len(bundle.players),
        candidate_pool_size=bundle.candidate_pool_size,
        positions=["QB", "RB", "WR", "TE"],
        rookie_mode=bundle.rookie_mode,
        scoring=scoring_export,
        league_defaults=league_export,
        sources=sources or [],
        pipeline=pipeline or [],
        limitations=default_limitations + bundle.warnings,
        package_versions=package_versions(),
    )
