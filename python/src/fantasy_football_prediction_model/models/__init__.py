"""Modelling: baselines, candidates, preprocessing, uncertainty, registry.

Heavy modules such as ``training`` are imported by callers directly so package
init stays free of evaluation↔models circular imports.
"""

from fantasy_football_prediction_model.models.baselines import (
    BASELINE_REGISTRY,
    BaselineModel,
)
from fantasy_football_prediction_model.models.preprocessing import (
    FeatureMatrix,
    FoldPreprocessor,
)

__all__ = [
    "BASELINE_REGISTRY",
    "BaselineModel",
    "FeatureMatrix",
    "FoldPreprocessor",
]
