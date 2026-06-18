"""Pipeline backend Flask application composition."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request

from backend.pipeline_api import PipelineApi
from backend.pipeline_service import PipelineRunService, RunRegistry

PipelineCallable = Callable[..., dict[str, Any]]


def CreateBackendApp(
    *,
    pipelineCallable: PipelineCallable | None = None,
    debugRunsRoot: Path | None = None,
    allowedFrontendOrigins: Sequence[str] = (),
) -> Flask:
    if pipelineCallable is None:
        from agents.document_pipeline import run_document_pipeline

        pipelineCallable = run_document_pipeline

    registry = RunRegistry()
    service = PipelineRunService(
        registry=registry,
        pipelineCallable=pipelineCallable,
    )
    pipelineApi = PipelineApi(
        registry=registry,
        service=service,
        debugRunsRoot=debugRunsRoot,
    )

    app = Flask(__name__)
    pipelineApi.RegisterRoutes(app)
    _RegisterCors(app, allowedFrontendOrigins)

    @app.get("/api/health")
    def read_health() -> Any:
        return jsonify({"status": "ok"})

    return app


def _RegisterCors(app: Flask, allowedOrigins: Sequence[str]) -> None:
    allowed = frozenset(origin.rstrip("/") for origin in allowedOrigins if origin)

    @app.after_request
    def add_cors_headers(response: Any) -> Any:
        origin = (request.headers.get("Origin") or "").rstrip("/")
        if origin not in allowed:
            return response
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Headers"] = (
            "Content-Type, Last-Event-ID"
        )
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Max-Age"] = "600"
        return response
