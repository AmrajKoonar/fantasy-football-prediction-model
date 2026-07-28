# Methodology

## Objective

Use information available through season `t` to predict season `t+1` football statistics for QB, RB, WR and TE, then convert those statistics into fantasy points and value-based draft ranks.

## Dataset construction

1. Aggregate weekly nflverse stats to player-seasons.
2. Attach team context, availability, depth and optional advanced sources known by the end of season `t`.
3. Form modelling pairs: features from the player’s most recent season before outcome season `S`, plus week-1 team for `S` when known.
4. Absent next-season stats become genuine zeros for candidates (survivorship handling).

## Feature research

Coverage, year-over-year stability and next-season correlations are computed by `ffpm research features`. Features are not included merely because they sound advanced.

## Models

Baselines (prior season, rates, weighted averages, age-group means, ridge, opportunity medians) compete with Ridge, Elastic Net, forests, HistGradientBoosting and optional LightGBM/XGBoost. Selection uses rolling-origin backtests.

## Uncertainty

Default residual intervals (20th / 50th / 80th) calibrated by opportunity tier. Confidence scores trust in the estimate, not player quality.

## Fantasy and VORP

Default full PPR. Client recalculates scoring. Overall draft order defaults to value over replacement with documented flex demand allocation and deterministic tie-breakers.
