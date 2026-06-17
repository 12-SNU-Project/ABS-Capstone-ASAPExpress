"""Dash callback registration grouped by UI feature boundary."""

from __future__ import annotations

from dash import Dash

from backend import PipelineApi
from frontend.callbacks.classification import RegisterClassificationCallbacks
from frontend.callbacks.document_package import RegisterDocumentPackageCallbacks
from frontend.callbacks.navigation import RegisterNavigationCallbacks
from frontend.callbacks.routing import RegisterRoutingCallbacks
from frontend.callbacks.runtime import RegisterRuntimeCallbacks


def RegisterFrontendCallbacks(app: Dash, pipelineApi: PipelineApi) -> None:
    RegisterRuntimeCallbacks(app)
    RegisterNavigationCallbacks(app)
    RegisterDocumentPackageCallbacks(app)
    RegisterClassificationCallbacks(app)
    RegisterRoutingCallbacks(app, pipelineApi)
