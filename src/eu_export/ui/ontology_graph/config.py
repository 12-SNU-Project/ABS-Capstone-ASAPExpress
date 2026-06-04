"""Ontology graph UI configuration."""

from pathlib import Path


PROJECT_ROOT_PATH = Path(__file__).resolve().parents[4]
DEFAULT_SUMMARY_PATH = (
    PROJECT_ROOT_PATH / "artifacts" / "ontology-smoke" / "runtime-smoke-summary.json"
)
DEFAULT_ONTOLOGY_ROOT_PATH = PROJECT_ROOT_PATH / "eu_export_ontology_v1"
DEFAULT_PRODUCT_GRAPH_ARTIFACT_ROOT_PATH = (
    PROJECT_ROOT_PATH / "artifacts" / "ontology-graph-ui"
)
DEFAULT_UI_TOP_K = 5
DEFAULT_UI_MAX_OCR_IMAGE_COUNT = 8
DEFAULT_UI_KURLY_TIMEOUT_SECONDS = 60

PYSIDE_INSTALL_GUIDE = """\
PySide6가 현재 conda 환경에 설치되어 있지 않습니다.

1차 후보 계층 GUI를 실행하려면 다음 명령으로 설치하세요.

  conda install -n asap_pw -c conda-forge pyside6

설치 후 다시 실행:

  conda run -n asap_pw python ontology_graph_ui.py
"""

