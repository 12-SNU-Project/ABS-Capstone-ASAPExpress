"""HTTP client used by the Dash presentation server."""

from __future__ import annotations

from urllib.parse import quote

import requests


class PipelineApiClient:
    def __init__(
        self,
        baseUrl: str,
        *,
        timeoutSeconds: float = 15.0,
    ) -> None:
        normalizedBaseUrl = baseUrl.strip().rstrip("/")
        if not normalizedBaseUrl.startswith(("http://", "https://")):
            raise ValueError("Pipeline API base URL must be an HTTP(S) URL.")
        if timeoutSeconds <= 0:
            raise ValueError("Pipeline API timeout must be positive.")
        self._baseUrl = normalizedBaseUrl
        self._timeoutSeconds = timeoutSeconds

    def ReadDocumentPackageDetail(
        self,
        runId: str,
        packageId: str,
    ) -> dict[str, object]:
        return self._GetJson(
            "/api/runs/{0}/document-packages/{1}".format(
                quote(runId, safe=""),
                quote(packageId, safe=""),
            )
        )

    def ReadAdminRunDebug(self, runId: str) -> dict[str, object]:
        return self._GetJson(
            "/api/admin/runs/{0}".format(quote(runId, safe="")),
        )

    def _GetJson(self, path: str) -> dict[str, object]:
        response = requests.get(
            f"{self._baseUrl}{path}",
            timeout=self._timeoutSeconds,
        )
        if response.status_code == 404:
            return {}
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Pipeline API response must be a JSON object.")
        return payload
