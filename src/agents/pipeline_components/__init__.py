"""Reusable pipeline components used by Kurly/document flows.

Modules are grouped by pipeline stage for import clarity:
- Evidence intake
- Product understanding (identity + composition)
- HS2 pre-routing
- Staged HS4 -> HS6 -> CN8 classification
- TARIC branch resolution
"""

from __future__ import annotations

import sys

from bussiness_logic.pipeline.components import classification
from bussiness_logic.pipeline.components import evidence_intake
from bussiness_logic.pipeline.components import hs2_routing
from bussiness_logic.pipeline.components import product_understanding
from bussiness_logic.pipeline.components import taric_branch_resolution
from bussiness_logic.pipeline.components.classification import ClassificationComponent
from bussiness_logic.pipeline.components.evidence_intake import EvidenceIntakeComponent
from bussiness_logic.pipeline.components.hs2_routing import Hs2RoutingComponent
from bussiness_logic.pipeline.components.product_understanding import (
    ProductUnderstandingComponent,
)
from bussiness_logic.pipeline.components.taric_branch_resolution import (
    TaricBranchResolutionComponent,
)

sys.modules[__name__ + ".classification"] = classification
sys.modules[__name__ + ".evidence_intake"] = evidence_intake
sys.modules[__name__ + ".hs2_routing"] = hs2_routing
sys.modules[__name__ + ".product_understanding"] = product_understanding
sys.modules[__name__ + ".taric_branch_resolution"] = taric_branch_resolution

__all__ = [
    "ClassificationComponent",
    "EvidenceIntakeComponent",
    "Hs2RoutingComponent",
    "ProductUnderstandingComponent",
    "TaricBranchResolutionComponent",
]
