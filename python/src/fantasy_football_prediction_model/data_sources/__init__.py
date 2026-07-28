"""Adapters for every external data source, plus the shared on-disk cache.

Each adapter is responsible for downloading only what was asked for, caching
successful responses, retrying transient failures, validating that the schema
still looks the way the pipeline expects, and recording provenance.

No adapter is ever allowed to invent a value. When a source is unavailable it
either raises :class:`~fantasy_football_prediction_model.logging.DataUnavailableError`
(required data) or returns ``None`` with a logged warning (optional data).
"""

from fantasy_football_prediction_model.data_sources.local_cache import (
    CacheEntry,
    DataCache,
)

__all__ = ["CacheEntry", "DataCache"]
