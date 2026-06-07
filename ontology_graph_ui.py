"""Ontology candidate hierarchy graph UI root entrypoint."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT_PATH = Path(__file__).resolve().parent
SOURCE_ROOT_PATH = PROJECT_ROOT_PATH / "src"
if str(SOURCE_ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT_PATH))

from eu_export.ui.ontology_graph import (  # noqa: E402
    RunOntologyGraphUi,
)


def Main() -> int:
    return RunOntologyGraphUi()


if __name__ == "__main__":
    raise SystemExit(Main())
