"""ASAP pipeline backend entrypoint."""

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

from backend.app import CreateBackendApp
from bussiness_logic.app_config import LoadAppConfig


appConfig = LoadAppConfig(ASAP_ROOT)
app = CreateBackendApp(
    debugRunsRoot=appConfig.paths.ResolvePath(
        ASAP_ROOT,
        appConfig.paths.blackboard_runs_root,
    ),
    allowedFrontendOrigins=appConfig.web.allowed_frontend_origins,
)
server = app


if __name__ == "__main__":
    app.run(
        debug=False,
        host=appConfig.web.backend_host,
        port=appConfig.web.backend_port,
        threaded=True,
    )
