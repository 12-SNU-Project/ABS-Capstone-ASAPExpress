"""Dash callback registration grouped by UI feature boundary."""

from __future__ import annotations

from dash import Dash

from frontend.callbacks.classification import RegisterClassificationCallbacks
from frontend.callbacks.document_package import RegisterDocumentPackageCallbacks
from frontend.callbacks.navigation import RegisterNavigationCallbacks
from frontend.callbacks.routing import RegisterRoutingCallbacks
from frontend.callbacks.runtime import RegisterRuntimeCallbacks
from frontend.pipeline_api_client import PipelineApiClient


def RegisterFrontendCallbacks(
    app: Dash,
    pipelineApiClient: PipelineApiClient,
) -> None:
    RegisterRuntimeCallbacks(app)
    RegisterNavigationCallbacks(app)
    RegisterDocumentPackageCallbacks(app)
    RegisterClassificationCallbacks(app)
    RegisterRoutingCallbacks(app, pipelineApiClient)
