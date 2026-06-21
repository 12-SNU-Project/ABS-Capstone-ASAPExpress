"""ASAP Dash application entrypoint."""

from __future__ import annotations

import os
import sys
from pathlib import Path


ASAP_ROOT = Path(
    os.environ.get("ASAP_PROJECT_ROOT", Path(__file__).resolve().parent),
).resolve()
ASAP_SRC_ROOT = ASAP_ROOT / "src"
for searchPath in (ASAP_ROOT, ASAP_SRC_ROOT):
    if searchPath.exists() and str(searchPath) not in sys.path:
        sys.path.insert(0, str(searchPath))

from frontend import CreateDashApp
from bussiness_logic.app_config import LoadAppConfig


appConfig = LoadAppConfig(ASAP_ROOT)
app = CreateDashApp(
    apiBaseUrl=appConfig.web.backend_api_base_url,
    apiRequestTimeoutSeconds=appConfig.web.backend_request_timeout_seconds,
)
server = app.server

# instruct gpt
# RAG -> DPO 기법 -> Survey 기법
# 그래프 구조 메커니즘
#
if __name__ == "__main__":
    app.run(
        debug=False,
        host=appConfig.web.frontend_host,
        port=appConfig.web.frontend_port,
    )
