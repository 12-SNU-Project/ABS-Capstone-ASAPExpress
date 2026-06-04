"""비밀값이 아닌 앱 실행 설정을 읽는 helper."""

from pathlib import Path
from typing import Any, Mapping, Optional

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


def ReadConfigSection(
    appConfig: Mapping[str, Any],
    sectionName: str,
) -> Mapping[str, Any]:
    sectionData = appConfig.get(sectionName)
    if isinstance(sectionData, Mapping):
        return sectionData
    return {}


def ReadConfigBool(
    sectionData: Mapping[str, Any],
    key: str,
    defaultValue: bool,
) -> bool:
    value = sectionData.get(key)
    if isinstance(value, bool):
        return value
    return defaultValue


def ReadConfigInt(
    sectionData: Mapping[str, Any],
    key: str,
    defaultValue: int,
) -> int:
    value = sectionData.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return defaultValue


def ReadConfigStringList(
    sectionData: Mapping[str, Any],
    key: str,
    defaultValue: list[str],
) -> list[str]:
    value = sectionData.get(key)
    if not isinstance(value, list):
        return list(defaultValue)
    return [item for item in value if isinstance(item, str) and item.strip() != ""]


def ReadConfigPath(
    sectionData: Mapping[str, Any],
    key: str,
    projectRootPath: str | Path,
    defaultValue: str,
) -> Path:
    value = sectionData.get(key)
    rawPath = value if isinstance(value, str) and value.strip() != "" else defaultValue
    resolvedPath = Path(rawPath).expanduser()
    if resolvedPath.is_absolute():
        return resolvedPath
    return Path(projectRootPath) / resolvedPath
