"""ASAP core smoke Stage5 PySide desktop entrypoint.

Run:
  python asap_pyside.py
"""
from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
SRC_ROOT = PROJECT_ROOT / "src"
for _path in (PROJECT_ROOT, SRC_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))


def main() -> None:
    try:
        from ui.pyside_app import RunPysideApp
    except ModuleNotFoundError as exc:
        if exc.name == "PySide6":
            raise SystemExit(
                "PySide6가 설치되어 있지 않습니다. 현재 env에서 `pip install PySide6` 후 다시 실행하세요."
            ) from exc
        raise

    raise SystemExit(RunPysideApp(sys.argv))


if __name__ == "__main__":
    main()
