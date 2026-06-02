"""Ontology graph UI application entrypoint."""

import sys

from eu_export.ui.ontology_graph.config import (
    DEFAULT_SUMMARY_PATH,
    PYSIDE_INSTALL_GUIDE,
)


def RunOntologyGraphUi() -> int:
    try:
        from eu_export.ui.ontology_graph.qt_window import (
            QApplication,
            CandidateGraphWindow,
        )
    except ModuleNotFoundError as error:
        if error.name == "PySide6":
            print(PYSIDE_INSTALL_GUIDE)
            return 2
        raise

    app = QApplication(sys.argv)
    window = CandidateGraphWindow(DEFAULT_SUMMARY_PATH)
    window.show()
    return int(app.exec())

