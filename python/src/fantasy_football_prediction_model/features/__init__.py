"""Feature engineering.

The contract every function in this package honours:

**A feature attached to season ``t`` may use information known by the end of
season ``t``, plus explicitly identified preseason information about season
``t + 1``.**

The only preseason information used is the player's week-1 team for the
projected season, which drives the team-change signal and decides whose team
context is attached. That is genuinely known before a snap is played. It is
documented in ``docs/METHODOLOGY.md`` and enforced by the leakage tests in
``evaluation/leakage.py``.

Nothing else about season ``t + 1`` may enter a feature. No outcome, no games
played, no final roster, no depth chart published during the season.
"""

from fantasy_football_prediction_model.features.common import (
    FeatureBuildResult,
    build_feature_table,
)

__all__ = ["FeatureBuildResult", "build_feature_table"]
