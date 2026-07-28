"""Deterministic template-based projection explanations."""

from __future__ import annotations

from typing import Any

from fantasy_football_prediction_model.schemas import ExplanationBlock, ExplanationFactor


FEATURE_LABELS: dict[str, str] = {
    "targets": "Targets",
    "target_share": "Target share",
    "targets_per_game": "Targets per game",
    "receptions": "Receptions",
    "receiving_yards": "Receiving yards",
    "carries": "Carries",
    "carry_share": "Carry share",
    "rushing_yards": "Rushing yards",
    "pass_attempts": "Pass attempts",
    "passing_yards": "Passing yards",
    "fantasy_points_ppr": "Prior PPR points",
    "fantasy_points_ppr_per_game": "Prior PPR points per game",
    "snap_share": "Snap share",
    "route_participation": "Route participation",
    "yards_per_route_run": "Yards per route run",
    "age_at_target_season": "Age",
    "experience_at_target_season": "Experience",
    "draft_pick": "Draft capital",
    "team_change": "Team change",
    "seasons_since_last_played": "Time since last season",
    "wopr": "WOPR",
    "air_yards_share": "Air-yard share",
    "red_zone_targets": "Red-zone targets",
    "goal_line_carries": "Goal-line carries",
}


def _label(feature: str) -> str:
    return FEATURE_LABELS.get(feature, feature.replace("_", " ").title())


def build_explanation(
    *,
    feature_values: dict[str, float | None],
    contributions: dict[str, float] | None = None,
    top_n: int = 4,
    min_relative: float = 0.12,
    method: str = "unavailable",
    rookie: bool = False,
) -> ExplanationBlock:
    """Build positive/negative factors from contributions or feature percentiles."""
    contributions = dict(contributions or {})
    if not contributions:
        # Fallback: treat larger opportunity features as optimistic signals.
        for key in (
            "target_share",
            "targets",
            "carry_share",
            "carries",
            "pass_attempts",
            "fantasy_points_ppr",
            "snap_share",
            "wopr",
        ):
            value = feature_values.get(key)
            if value is not None:
                contributions[key] = float(value)

    if not contributions:
        summary = (
            "Rookie projection based on draft capital and landing-spot context."
            if rookie
            else "Insufficient feature attribution was available for a detailed explanation."
        )
        return ExplanationBlock(
            summary=summary,
            method="unavailable",  # type: ignore[arg-type]
            optimistic_note="",
            cautious_note="Wide historical intervals or sparse data reduce confidence.",
        )

    ranked = sorted(contributions.items(), key=lambda item: abs(item[1]), reverse=True)
    peak = max(abs(v) for _, v in ranked) or 1.0
    positive: list[ExplanationFactor] = []
    negative: list[ExplanationFactor] = []
    for feature, contribution in ranked:
        if abs(contribution) / peak < min_relative:
            continue
        value = feature_values.get(feature)
        factor = ExplanationFactor(
            feature=feature,
            label=_label(feature),
            value=float(value) if value is not None else None,
            display_value=f"{value:.2f}" if isinstance(value, (int, float)) else None,
            contribution=float(contribution),
            direction="positive" if contribution >= 0 else "negative",
            description=(
                f"{_label(feature)} contributed to the projection "
                f"({'upside' if contribution >= 0 else 'downside'} signal)."
            ),
        )
        if contribution >= 0:
            positive.append(factor)
        else:
            negative.append(factor)
        if len(positive) + len(negative) >= top_n * 2:
            break

    positive = positive[:top_n]
    negative = negative[:top_n]
    optimistic = ", ".join(f.label for f in positive) or "stable recent usage"
    cautious = ", ".join(f.label for f in negative) or "role or supporting-cast uncertainty"
    summary = (
        f"Associated with {optimistic}. Caution associated with {cautious}."
    )
    return ExplanationBlock(
        positive_factors=positive,
        negative_factors=negative,
        summary=summary,
        optimistic_note=f"Why the model is optimistic: {optimistic}.",
        cautious_note=f"Why the model is cautious: {cautious}.",
        method=method if method in {"shap", "permutation", "unavailable"} else "unavailable",  # type: ignore[arg-type]
    )


def contributions_from_coefficients(
    feature_values: dict[str, float | None],
    coefficients: dict[str, float],
) -> dict[str, float]:
    """Approximate contribution as coefficient × centred value."""
    out: dict[str, float] = {}
    for feature, coef in coefficients.items():
        value = feature_values.get(feature)
        if value is None:
            continue
        out[feature] = float(coef) * float(value)
    return out
