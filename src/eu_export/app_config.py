"""비밀값이 아닌 앱 실행 설정을 TOML dict로 읽는다."""

from pathlib import Path
from typing import Any, Optional

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 이하 fallback 안내용
    tomllib = None  # type: ignore[assignment]


APP_CONFIG_FILE_NAME = ".appconfig"


def LoadAppConfig(
    projectRootPath: str | Path,
    configPath: Optional[str | Path] = None,
) -> dict[str, Any]:
    resolvedProjectRootPath = Path(projectRootPath)
    if configPath is not None:
        rawConfigPath = Path(configPath).expanduser()
        resolvedConfigPath = (
            rawConfigPath
            if rawConfigPath.is_absolute()
            else resolvedProjectRootPath / rawConfigPath
        )
    else:
        resolvedConfigPath = resolvedProjectRootPath / APP_CONFIG_FILE_NAME
    if not resolvedConfigPath.exists():
        return {}
    if tomllib is None:
        raise RuntimeError("Python 3.11+ tomllib is required to read .appconfig.")

    with resolvedConfigPath.open("rb") as configFile:
        configData = tomllib.load(configFile)
    if not isinstance(configData, dict):
        return {}
    return configData
