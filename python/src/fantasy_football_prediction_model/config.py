"""Typed configuration loaded from ``configs/*.yml``.

Every configuration file is parsed into a Pydantic model at startup. A field
that is missing, mistyped or internally inconsistent raises immediately with a
message naming the offending file, rather than surfacing as a confusing error
somewhere deep in the modelling code.

Precedence, highest first:

1. explicit CLI flags
2. ``FFPM_*`` environment variables
3. the YAML files
4. the model defaults in this module
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from fantasy_football_prediction_model.constants import FANTASY_POSITIONS

# ---------------------------------------------------------------------------
# Repository location
# ---------------------------------------------------------------------------


def find_repo_root(start: Path | None = None) -> Path:
    """Return the repository root.

    Walks upward looking for the ``configs`` directory that sits beside the
    ``python`` package. Falls back to the current working directory so the CLI
    still runs from an installed wheel outside a checkout.
    """
    if env_root := os.environ.get("FFPM_REPO_ROOT"):
        return Path(env_root).resolve()

    current = (start or Path(__file__)).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "configs" / "project.yml").is_file():
            return candidate
    return Path.cwd().resolve()


REPO_ROOT = find_repo_root()
CONFIG_DIR = REPO_ROOT / "configs"


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(
            f"Configuration file not found: {path}. "
            f"Expected it under {CONFIG_DIR}. Run the CLI from the repository root, "
            f"or set FFPM_REPO_ROOT."
        )
    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    if not isinstance(loaded, dict):
        raise ValueError(f"Configuration file {path} must contain a YAML mapping at the top level.")
    return loaded


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ---------------------------------------------------------------------------
# project.yml
# ---------------------------------------------------------------------------


class ProjectSettings(_Base):
    data_start_season: int = Field(ge=1999, le=2100)
    feature_end_season: int = Field(ge=1999, le=2100)
    target_season: int = Field(ge=2000, le=2100)
    output_player_count: int = Field(ge=1, le=2000)
    positions: list[str]
    random_seed: int = Field(ge=0)
    schema_version: str
    model_version: str
    projection_release: str

    @model_validator(mode="after")
    def _check_seasons(self) -> ProjectSettings:
        if self.feature_end_season < self.data_start_season:
            raise ValueError(
                f"feature_end_season ({self.feature_end_season}) must be >= "
                f"data_start_season ({self.data_start_season})."
            )
        if self.target_season != self.feature_end_season + 1:
            raise ValueError(
                f"target_season ({self.target_season}) must be exactly one season after "
                f"feature_end_season ({self.feature_end_season}). Predicting further ahead "
                f"is not supported: the model is trained on season t -> season t+1 pairs."
            )
        unknown = sorted(set(self.positions) - set(FANTASY_POSITIONS))
        if unknown:
            raise ValueError(f"Unsupported positions in project.positions: {unknown}.")
        if not self.positions:
            raise ValueError("project.positions must not be empty.")
        return self


class PathSettings(_Base):
    data_dir: str
    raw_dir: str
    cache_dir: str
    interim_dir: str
    processed_dir: str
    manual_dir: str
    manifest_dir: str
    artifacts_dir: str
    model_dir: str
    evaluation_dir: str
    feature_research_dir: str
    projection_dir: str
    web_data_dir: str

    def resolve(self, name: str) -> Path:
        """Return an absolute path for one of the configured directories."""
        raw = getattr(self, name)
        path = Path(raw)
        return path if path.is_absolute() else (REPO_ROOT / path).resolve()


class IngestionSettings(_Base):
    cache_ttl_hours: float = Field(ge=0)
    max_retries: int = Field(ge=0, le=20)
    backoff_initial_seconds: float = Field(gt=0)
    backoff_max_seconds: float = Field(gt=0)
    request_timeout_seconds: float = Field(gt=0)
    offline: bool
    required_datasets: list[str]
    optional_datasets: list[str]

    @model_validator(mode="after")
    def _check_backoff(self) -> IngestionSettings:
        if self.backoff_max_seconds < self.backoff_initial_seconds:
            raise ValueError("backoff_max_seconds must be >= backoff_initial_seconds.")
        overlap = set(self.required_datasets) & set(self.optional_datasets)
        if overlap:
            raise ValueError(f"Datasets listed as both required and optional: {sorted(overlap)}.")
        return self


class LoggingSettings(_Base):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    file_logging: bool
    log_dir: str


class OverrideSettings(_Base):
    apply_factual_corrections: bool
    apply_projection_overrides: bool
    apply_offseason_transactions: bool = True
    exclude_unsigned_from_rankings: bool = True
    factual_corrections_file: str
    projection_overrides_file: str
    id_corrections_file: str
    offseason_transactions_file: str = "data/manual/2026_offseason_transactions.csv"
    ranking_inclusions_file: str = "data/manual/ranking-inclusions.csv"


class ProjectConfig(_Base):
    project: ProjectSettings
    paths: PathSettings
    ingestion: IngestionSettings
    logging: LoggingSettings
    overrides: OverrideSettings


# ---------------------------------------------------------------------------
# scoring.yml
# ---------------------------------------------------------------------------


class PassingScoring(_Base):
    yards_per_point: float = Field(gt=0)
    touchdown: float
    interception: float
    two_point_conversion: float


class RushingScoring(_Base):
    yards_per_point: float = Field(gt=0)
    touchdown: float
    two_point_conversion: float


class ReceivingScoring(_Base):
    reception: float
    yards_per_point: float = Field(gt=0)
    touchdown: float
    two_point_conversion: float


class MiscScoring(_Base):
    fumble_lost: float


class ScoringRules(_Base):
    passing: PassingScoring
    rushing: RushingScoring
    receiving: ReceivingScoring
    misc: MiscScoring


class ScoringPreset(_Base):
    label: str
    description: str
    rules: ScoringRules


class BonusSettings(_Base):
    enabled: bool
    passing_yards_300_bonus: float
    rushing_yards_100_bonus: float
    receiving_yards_100_bonus: float


class ScoringConfig(_Base):
    default_preset: str
    presets: dict[str, ScoringPreset]
    bonuses: BonusSettings

    @model_validator(mode="after")
    def _check_default(self) -> ScoringConfig:
        if self.default_preset not in self.presets:
            raise ValueError(
                f"scoring.default_preset '{self.default_preset}' is not one of "
                f"{sorted(self.presets)}."
            )
        return self

    @property
    def default_rules(self) -> ScoringRules:
        return self.presets[self.default_preset].rules


# ---------------------------------------------------------------------------
# league-defaults.yml
# ---------------------------------------------------------------------------


class StarterSettings(_Base):
    qb: int = Field(ge=0, le=4)
    rb: int = Field(ge=0, le=6)
    wr: int = Field(ge=0, le=8)
    te: int = Field(ge=0, le=4)
    flex: int = Field(ge=0, le=6)
    superflex: int = Field(ge=0, le=2)


class LeagueSettings(_Base):
    teams: int = Field(ge=2, le=32)
    starters: StarterSettings
    bench_size: int = Field(ge=0, le=30)


class ReplacementSettings(_Base):
    method: Literal["demand_based", "fixed_rank"]
    fixed_rank: dict[str, int]
    smoothing_window: int = Field(ge=1, le=15)
    min_players_per_position: int = Field(ge=1)

    @model_validator(mode="after")
    def _check_positions(self) -> ReplacementSettings:
        missing = sorted(set(FANTASY_POSITIONS) - set(self.fixed_rank))
        if missing:
            raise ValueError(f"replacement.fixed_rank is missing positions: {missing}.")
        return self


class RiskSettings(_Base):
    penalty_weight: float = Field(ge=0, le=5)


class TierSettings(_Base):
    method: Literal["gap", "quantile"]
    gap_sigma: float = Field(gt=0)
    max_tiers: int = Field(ge=1, le=50)
    min_tier_size: int = Field(ge=1)


class LeagueConfig(_Base):
    league: LeagueSettings
    replacement: ReplacementSettings
    risk: RiskSettings
    tiers: TierSettings


# ---------------------------------------------------------------------------
# model.yml
# ---------------------------------------------------------------------------


class BacktestSettings(_Base):
    first_test_season: int
    last_test_season: int
    window: Literal["expanding", "sliding"]
    sliding_window_seasons: int = Field(ge=2)
    min_train_rows: int = Field(ge=10)
    rank_top_k: list[int]

    @model_validator(mode="after")
    def _check_range(self) -> BacktestSettings:
        if self.last_test_season < self.first_test_season:
            raise ValueError("backtest.last_test_season must be >= first_test_season.")
        if any(k <= 0 for k in self.rank_top_k):
            raise ValueError("backtest.rank_top_k values must be positive.")
        return self

    @property
    def test_seasons(self) -> list[int]:
        return list(range(self.first_test_season, self.last_test_season + 1))


class CandidateSettings(_Base):
    enabled: bool
    algorithm: str
    optional_dependency: str | None = None
    top_k: int | None = None


class TuningSettings(_Base):
    enabled: bool
    strategy: Literal["randomized", "grid", "none"]
    n_iter: int = Field(ge=1, le=500)
    inner_holdout_seasons: int = Field(ge=1, le=6)
    n_jobs: int
    search_space: dict[str, dict[str, list[Any]]]


class ArchitectureSettings(_Base):
    compare: list[Literal["direct", "component"]]
    relative_tolerance: float = Field(ge=0, le=1)
    default: Literal["direct", "component"]

    @model_validator(mode="after")
    def _check_default(self) -> ArchitectureSettings:
        if not self.compare:
            raise ValueError("architecture.compare must list at least one architecture.")
        if self.default not in self.compare:
            raise ValueError(
                f"architecture.default '{self.default}' must appear in architecture.compare."
            )
        return self


class WinsorizeSettings(_Base):
    enabled: bool
    lower_quantile: float = Field(ge=0, lt=0.5)
    upper_quantile: float = Field(gt=0.5, le=1.0)


class PreprocessingSettings(_Base):
    numeric_imputer: Literal["median", "mean", "zero"]
    add_missing_indicators: bool
    min_volume: dict[str, float]
    winsorize: WinsorizeSettings
    scale_linear_models: bool


class ConfidenceSettings(_Base):
    weights: dict[str, float]
    labels: dict[str, float]

    @model_validator(mode="after")
    def _check_weights(self) -> ConfidenceSettings:
        total = sum(self.weights.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"uncertainty.confidence.weights must sum to 1.0, got {total:.6f}. "
                f"Weights: {self.weights}."
            )
        if not {"high", "medium"} <= set(self.labels):
            raise ValueError("uncertainty.confidence.labels must define 'high' and 'medium'.")
        if self.labels["high"] <= self.labels["medium"]:
            raise ValueError("Confidence label threshold 'high' must exceed 'medium'.")
        return self


class UncertaintySettings(_Base):
    quantiles: list[float]
    method: Literal["residual", "quantile_model"]
    opportunity_tiers: int = Field(ge=1, le=10)
    min_bucket_size: int = Field(ge=1)
    confidence: ConfidenceSettings

    @model_validator(mode="after")
    def _check_quantiles(self) -> UncertaintySettings:
        if len(self.quantiles) != 3:
            raise ValueError(
                "uncertainty.quantiles must contain exactly three values (low, median, high)."
            )
        if sorted(self.quantiles) != self.quantiles:
            raise ValueError("uncertainty.quantiles must be sorted ascending.")
        if not all(0 < q < 1 for q in self.quantiles):
            raise ValueError("uncertainty.quantiles must all lie strictly between 0 and 1.")
        if abs(self.quantiles[1] - 0.5) > 1e-9:
            raise ValueError("The middle value of uncertainty.quantiles must be the median, 0.5.")
        return self

    @property
    def low_quantile(self) -> float:
        return self.quantiles[0]

    @property
    def high_quantile(self) -> float:
        return self.quantiles[2]


class ConstraintSettings(_Base):
    enabled: bool
    fallback_games_per_season: int = Field(ge=1, le=25)
    historical_max_multiplier: float = Field(ge=1.0, le=3.0)
    min_games: float = Field(ge=0)
    enforce: list[str]


class ExplanationSettings(_Base):
    method: Literal["auto", "shap", "permutation"]
    top_factors: int = Field(ge=1, le=20)
    permutation_repeats: int = Field(ge=1, le=50)
    min_relative_contribution: float = Field(ge=0, le=1)


class ModelConfig(_Base):
    backtest: BacktestSettings
    candidates: dict[str, CandidateSettings]
    tuning: TuningSettings
    architecture: ArchitectureSettings
    preprocessing: PreprocessingSettings
    uncertainty: UncertaintySettings
    constraints: ConstraintSettings
    explanations: ExplanationSettings

    @model_validator(mode="after")
    def _check_search_space(self) -> ModelConfig:
        unknown = sorted(set(self.tuning.search_space) - set(self.candidates))
        if unknown:
            raise ValueError(
                f"tuning.search_space references unknown candidates: {unknown}. "
                f"Known candidates: {sorted(self.candidates)}."
            )
        return self

    def enabled_candidates(self) -> dict[str, CandidateSettings]:
        return {name: spec for name, spec in self.candidates.items() if spec.enabled}


# ---------------------------------------------------------------------------
# features.yml
# ---------------------------------------------------------------------------


class FeatureGroup(_Base):
    description: str
    era_start: int
    required: bool
    features: list[str]


class SelectionSettings(_Base):
    min_coverage: float = Field(ge=0, le=1)
    min_target_correlation: float = Field(ge=0, le=1)
    max_pairwise_correlation: float = Field(gt=0, le=1)
    max_features_per_model: int = Field(ge=1, le=500)
    always_keep: list[str]


class FeatureConfig(_Base):
    groups: dict[str, FeatureGroup]
    position_groups: dict[str, list[str]]
    rookie_position_groups: dict[str, list[str]]
    selection: SelectionSettings

    @model_validator(mode="after")
    def _check_groups(self) -> FeatureConfig:
        known = set(self.groups)
        for mapping_name, mapping in (
            ("position_groups", self.position_groups),
            ("rookie_position_groups", self.rookie_position_groups),
        ):
            for position, group_names in mapping.items():
                if position not in FANTASY_POSITIONS:
                    raise ValueError(f"features.{mapping_name} has unknown position '{position}'.")
                unknown = sorted(set(group_names) - known)
                if unknown:
                    raise ValueError(
                        f"features.{mapping_name}.{position} references undefined groups: "
                        f"{unknown}."
                    )
        return self

    def candidate_features(self, position: str, *, rookie: bool = False) -> list[str]:
        """Return the ordered, de-duplicated candidate feature list for a model."""
        mapping = self.rookie_position_groups if rookie else self.position_groups
        names: list[str] = []
        seen: set[str] = set()
        for group_name in mapping.get(position, []):
            for feature in self.groups[group_name].features:
                if feature not in seen:
                    seen.add(feature)
                    names.append(feature)
        return names

    def group_for_feature(self, feature: str) -> str | None:
        for group_name, group in self.groups.items():
            if feature in group.features:
                return group_name
        return None

    def era_start_for_feature(self, feature: str) -> int | None:
        group_name = self.group_for_feature(feature)
        return self.groups[group_name].era_start if group_name else None


# ---------------------------------------------------------------------------
# Aggregate
# ---------------------------------------------------------------------------


def _env_bool(name: str) -> bool | None:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return None
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str) -> int | None:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name}={raw!r} is not an integer.") from exc


class Settings(_Base):
    """The fully validated configuration for one pipeline run."""

    project_config: ProjectConfig
    scoring: ScoringConfig
    league: LeagueConfig
    model: ModelConfig
    features: FeatureConfig
    config_dir: Path
    repo_root: Path

    # -- convenience accessors ------------------------------------------------

    @property
    def target_season(self) -> int:
        return self.project_config.project.target_season

    @property
    def feature_end_season(self) -> int:
        return self.project_config.project.feature_end_season

    @property
    def data_start_season(self) -> int:
        return self.project_config.project.data_start_season

    @property
    def seed(self) -> int:
        return self.project_config.project.random_seed

    @property
    def positions(self) -> list[str]:
        return list(self.project_config.project.positions)

    @property
    def paths(self) -> PathSettings:
        return self.project_config.paths

    def path(self, name: str) -> Path:
        return self.paths.resolve(name)

    def ensure_directories(self) -> None:
        """Create every output directory the pipeline writes to."""
        for name in (
            "raw_dir",
            "cache_dir",
            "interim_dir",
            "processed_dir",
            "manifest_dir",
            "model_dir",
            "evaluation_dir",
            "feature_research_dir",
            "projection_dir",
            "web_data_dir",
        ):
            self.path(name).mkdir(parents=True, exist_ok=True)

    @property
    def all_seasons(self) -> list[int]:
        """Every season with observed statistics, oldest first."""
        return list(range(self.data_start_season, self.feature_end_season + 1))


def load_settings(
    config_dir: Path | str | None = None,
    *,
    target_season: int | None = None,
    offline: bool | None = None,
    log_level: str | None = None,
) -> Settings:
    """Load, merge and validate every configuration file.

    Args:
        config_dir: Directory holding the YAML files. Defaults to ``configs/``.
        target_season: Overrides ``project.target_season``. ``feature_end_season``
            moves with it so the season-t to season-t+1 invariant holds.
        offline: Overrides ``ingestion.offline``.
        log_level: Overrides ``logging.level``.

    Raises:
        FileNotFoundError: a required configuration file is missing.
        pydantic.ValidationError: a configuration value is invalid.
    """
    directory = Path(config_dir) if config_dir else CONFIG_DIR
    directory = directory if directory.is_absolute() else (REPO_ROOT / directory).resolve()

    project_raw = _read_yaml(directory / "project.yml")

    env_season = _env_int("FFPM_TARGET_SEASON")
    effective_season = target_season if target_season is not None else env_season
    if effective_season is not None:
        project_raw["project"]["target_season"] = effective_season
        project_raw["project"]["feature_end_season"] = effective_season - 1

    env_offline = _env_bool("FFPM_OFFLINE")
    effective_offline = offline if offline is not None else env_offline
    if effective_offline is not None:
        project_raw["ingestion"]["offline"] = effective_offline

    effective_level = log_level or os.environ.get("FFPM_LOG_LEVEL")
    if effective_level:
        project_raw["logging"]["level"] = effective_level.upper()

    for env_name, key in (("FFPM_DATA_DIR", "data_dir"), ("FFPM_CACHE_DIR", "cache_dir")):
        if value := os.environ.get(env_name):
            project_raw["paths"][key] = value

    return Settings(
        project_config=ProjectConfig.model_validate(project_raw),
        scoring=ScoringConfig.model_validate(_read_yaml(directory / "scoring.yml")),
        league=LeagueConfig.model_validate(_read_yaml(directory / "league-defaults.yml")),
        model=ModelConfig.model_validate(_read_yaml(directory / "model.yml")),
        features=FeatureConfig.model_validate(_read_yaml(directory / "features.yml")),
        config_dir=directory,
        repo_root=REPO_ROOT,
    )


@lru_cache(maxsize=8)
def get_settings(config_dir: str | None = None) -> Settings:
    """Cached :func:`load_settings` for callers that need the plain defaults."""
    return load_settings(config_dir)
