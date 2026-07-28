"""fantasy-football-prediction-model.

A reproducible, free-to-run NFL fantasy-football projection system.

The package predicts individual offensive-player statistics for the next NFL
season from publicly available nflverse data, converts them into configurable
fantasy points, and exports validated JSON for a static Next.js frontend.

Nothing in this package fabricates data. When a source is unavailable the
pipeline logs the failure, preserves cached data where it can, and either
degrades in a documented way or raises with an actionable message.
"""

from __future__ import annotations

__version__ = "1.0.0"

__all__ = ["__version__"]
