"""Ingestion, validation, identity resolution, aggregation and manifests.

This layer turns raw nflverse downloads into clean, validated, canonically
keyed season tables. Everything downstream assumes:

* one row per ``(gsis_id, season)`` in the player tables,
* ``gsis_id`` resolves to exactly one real player,
* team abbreviations are normalised to current franchise codes,
* positions are normalised to QB / RB / WR / TE,
* no column silently changed meaning between seasons.
"""

from fantasy_football_prediction_model.data.identities import (
    PlayerIdentityResolver,
    normalise_name,
    normalise_position,
    normalise_team,
    slugify_name,
)

__all__ = [
    "PlayerIdentityResolver",
    "normalise_name",
    "normalise_position",
    "normalise_team",
    "slugify_name",
]
