"""Cost layer: weights, class substitution cost, attribute / edge / aggregate distances.

Everything in this package is a tuning decision of the distance.  It consumes
the representation (``ged.contract``) and never feeds back into it.
"""

from .config import CostConfig, FixedCostParts, GeometryTerm
from .default import default_config

__all__ = ["CostConfig", "FixedCostParts", "GeometryTerm", "default_config"]
