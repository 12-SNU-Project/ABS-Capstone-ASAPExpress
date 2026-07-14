"""Compatibility exports for moved pipeline components."""
from __future__ import annotations

import importlib
import sys

from bussiness_logic.pipeline import component_base as _component_base
from bussiness_logic.pipeline.component_base import BasePipelineComponent, ComponentResult

sys.modules[__name__ + ".component_base"] = _component_base
sys.modules[__name__ + ".coi_loader"] = importlib.import_module(
    "bussiness_logic.product.services.coi_loader",
)
sys.modules[__name__ + ".runtime_adapter"] = importlib.import_module(
    "bussiness_logic.bridge.runtime_adapter",
)

from agents.pipeline_components import (
    ClassificationComponent,
    EvidenceIntakeComponent,
    Hs2RoutingComponent,
    ProductUnderstandingComponent,
    TaricBranchResolutionComponent,
)
from bussiness_logic.document.document_component import DocumentComponent

__all__ = [
    "BasePipelineComponent",
    "ComponentResult",
    "EvidenceIntakeComponent",
    "ProductUnderstandingComponent",
    "Hs2RoutingComponent",
    "ClassificationComponent",
    "TaricBranchResolutionComponent",
    "DocumentComponent",
]
