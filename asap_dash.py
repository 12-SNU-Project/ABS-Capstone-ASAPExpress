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


app = CreateDashApp()
server = app.server


if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=8050)
