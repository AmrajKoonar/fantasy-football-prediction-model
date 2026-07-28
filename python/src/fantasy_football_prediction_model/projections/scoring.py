"""Configurable fantasy scoring from projected football statistics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from fantasy_football_prediction_model.config import ScoringConfig, ScoringRules


@dataclass(frozen=True, slots=True)
class ScoreBreakdown:
    """Transparent arithmetic for one scoring result."""

    total: float
    passing: float
    rushing: float
    receiving: float
    misc: float


def score_stats(stats: Mapping[str, float | None], rules: ScoringRules) -> ScoreBreakdown:
    """Score a mapping of snake_case or camelCase projected statistics."""
    def g(*keys: str) -> float:
        for key in keys:
            value = stats.get(key)
            if value is not None:
                return float(value)
        return 0.0

    passing_yards = g("passing_yards", "passingYards")
    passing_tds = g("passing_tds", "passing_touchdowns", "passingTouchdowns")
    interceptions = g("interceptions")
    rushing_yards = g("rushing_yards", "rushingYards")
    rushing_tds = g("rushing_tds", "rushing_touchdowns", "rushingTouchdowns")
    receptions = g("receptions")
    receiving_yards = g("receiving_yards", "receivingYards")
    receiving_tds = g("receiving_tds", "receiving_touchdowns", "receivingTouchdowns")
    fumbles = g("fumbles_lost", "fumblesLost")

    passing = 0.0
    if rules.passing.yards_per_point:
        passing += passing_yards / rules.passing.yards_per_point
    passing += passing_tds * rules.passing.touchdown
    passing += interceptions * rules.passing.interception

    rushing = 0.0
    if rules.rushing.yards_per_point:
        rushing += rushing_yards / rules.rushing.yards_per_point
    rushing += rushing_tds * rules.rushing.touchdown

    receiving = receptions * rules.receiving.reception
    if rules.receiving.yards_per_point:
        receiving += receiving_yards / rules.receiving.yards_per_point
    receiving += receiving_tds * rules.receiving.touchdown

    misc = fumbles * rules.misc.fumble_lost
    total = passing + rushing + receiving + misc
    return ScoreBreakdown(
        total=float(total),
        passing=float(passing),
        rushing=float(rushing),
        receiving=float(receiving),
        misc=float(misc),
    )


def score_total(stats: Mapping[str, float | None], rules: ScoringRules) -> float:
    return score_stats(stats, rules).total


def rules_from_preset(scoring: ScoringConfig, preset: str | None = None) -> ScoringRules:
    name = preset or scoring.default_preset
    if name not in scoring.presets:
        raise KeyError(f"Unknown scoring preset '{name}'. Known: {sorted(scoring.presets)}")
    return scoring.presets[name].rules


def rules_to_export_dict(rules: ScoringRules) -> dict[str, float]:
    return {
        "passing_yards_per_point": rules.passing.yards_per_point,
        "passing_touchdown": rules.passing.touchdown,
        "interception": rules.passing.interception,
        "passing_two_point": rules.passing.two_point_conversion,
        "rushing_yards_per_point": rules.rushing.yards_per_point,
        "rushing_touchdown": rules.rushing.touchdown,
        "rushing_two_point": rules.rushing.two_point_conversion,
        "reception": rules.receiving.reception,
        "receiving_yards_per_point": rules.receiving.yards_per_point,
        "receiving_touchdown": rules.receiving.touchdown,
        "receiving_two_point": rules.receiving.two_point_conversion,
        "fumble_lost": rules.misc.fumble_lost,
    }


def custom_rules(base: ScoringRules, overrides: dict[str, Any]) -> ScoringRules:
    """Return a copy of ``base`` with selected numeric overrides applied."""
    payload = {
        "passing": base.passing.model_dump(),
        "rushing": base.rushing.model_dump(),
        "receiving": base.receiving.model_dump(),
        "misc": base.misc.model_dump(),
    }
    mapping = {
        "reception": ("receiving", "reception"),
        "passing_yards_per_point": ("passing", "yards_per_point"),
        "passing_touchdown": ("passing", "touchdown"),
        "interception": ("passing", "interception"),
        "rushing_yards_per_point": ("rushing", "yards_per_point"),
        "receiving_yards_per_point": ("receiving", "yards_per_point"),
        "rushing_touchdown": ("rushing", "touchdown"),
        "receiving_touchdown": ("receiving", "touchdown"),
        "fumble_lost": ("misc", "fumble_lost"),
    }
    for key, value in overrides.items():
        if key in mapping:
            group, field = mapping[key]
            payload[group][field] = value
    return ScoringRules.model_validate(payload)
