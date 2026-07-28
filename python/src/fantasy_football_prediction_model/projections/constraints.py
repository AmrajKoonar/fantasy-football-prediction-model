"""Football consistency constraints on raw model output."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ConstraintDiagnostics:
    """Which fields were altered to enforce football consistency."""

    changes: list[dict[str, Any]] = field(default_factory=list)

    def record(self, field_name: str, before: float, after: float, rule: str) -> None:
        if abs(before - after) > 1e-9:
            self.changes.append(
                {
                    "field": field_name,
                    "before": before,
                    "after": after,
                    "rule": rule,
                }
            )


def apply_constraints(
    stats: dict[str, float | None],
    *,
    max_games: float = 17.0,
    min_games: float = 0.0,
    diagnostics: ConstraintDiagnostics | None = None,
) -> dict[str, float | None]:
    """Return a coherent copy of ``stats``.

    Enforces non-negativity for counts/yards, completions ≤ attempts,
    receptions ≤ targets, and games within the schedule length.
    """
    out: dict[str, float | None] = dict(stats)
    diag = diagnostics or ConstraintDiagnostics()

    def set_val(name: str, value: float, rule: str) -> None:
        before = float(out.get(name) or 0.0)
        out[name] = value
        diag.record(name, before, value, rule)

    for name in (
        "games",
        "pass_attempts",
        "completions",
        "passing_yards",
        "passing_tds",
        "interceptions",
        "carries",
        "rushing_yards",
        "rushing_tds",
        "targets",
        "receptions",
        "receiving_yards",
        "receiving_tds",
        "fumbles_lost",
    ):
        if name not in out or out[name] is None:
            continue
        value = float(out[name])
        if name.endswith("yards"):
            # Yards can theoretically be slightly negative historically; clamp at a soft floor.
            if value < -50:
                set_val(name, -50.0, "yards_floor")
        elif value < 0:
            set_val(name, 0.0, "non_negative")

    games = float(out.get("games") or 0.0)
    clipped_games = min(max(games, min_games), max_games)
    if games != clipped_games:
        set_val("games", clipped_games, "games_within_schedule")

    attempts = out.get("pass_attempts")
    completions = out.get("completions")
    if attempts is not None and completions is not None and completions > attempts:
        set_val("completions", float(attempts), "completions_le_attempts")

    targets = out.get("targets")
    receptions = out.get("receptions")
    if targets is not None and receptions is not None and receptions > targets:
        set_val("receptions", float(targets), "receptions_le_targets")

    return out


def enforce_quantile_ordering(low: float, median: float, high: float) -> tuple[float, float, float]:
    """Ensure low ≤ median ≤ high."""
    median = float(median)
    low = min(float(low), median)
    high = max(float(high), median)
    if low > high:
        low, high = high, low
    return low, median, high
