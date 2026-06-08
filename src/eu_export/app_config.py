"""비밀값이 아닌 앱 실행 설정을 TOML에서 Pydantic model로 읽는다."""

from pathlib import Path
from typing import Any, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
)

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 이하 fallback 안내용
    tomllib = None  # type: ignore[assignment]


APP_CONFIG_FILE_NAME = ".appconfig"
REASONING_EFFORT_VALUES = frozenset({"none", "minimal", "low", "medium", "high"})


class LlmAppConfig(BaseModel):
    """LLM runtime profile 설정."""

    model_config = ConfigDict(extra="ignore")

    runtime: Optional[StrictStr] = None
    provider: Optional[StrictStr] = None
    model: Optional[StrictStr] = None
    endpoint_url: Optional[StrictStr] = None
    chat_completions_path: Optional[StrictStr] = None
    timeout_seconds: Optional[StrictInt] = None
    supports_response_format: Optional[StrictBool] = None
    reasoning_effort: Optional[StrictStr] = None

    @field_validator("reasoning_effort")
    @classmethod
    def NormalizeReasoningEffort(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None

        normalizedValue = value.strip().lower()
        if normalizedValue not in REASONING_EFFORT_VALUES:
            raise ValueError(
                "reasoning_effort must be one of: {0}".format(
                    ", ".join(sorted(REASONING_EFFORT_VALUES)),
                )
            )
        return normalizedValue


class AppPathsConfig(BaseModel):
    """앱 실행 중 참조하는 경로 설정."""

    model_config = ConfigDict(extra="ignore")

    ontology_root: Path = Path("eu_export_ontology_v1")
    ontology_smoke_summary_artifact: Path = Path(
        "artifacts/ontology-smoke/runtime-smoke-summary.json",
    )
    ontology_human_review_package_artifact: Path = Path(
        "artifacts/ontology-smoke/stage1-human-review-package.json",
    )
    kurly_smoke_artifact_root: Path = Path("artifacts/kurly-market-smoke")
    kurly_smoke_summary_artifact: Path = Path(
        "artifacts/kurly-market-smoke/runtime-smoke-summary.json",
    )

    def ResolvePath(self, projectRootPath: str | Path, configPath: Path) -> Path:
        expandedPath = configPath.expanduser()
        if expandedPath.is_absolute():
            return expandedPath
        return Path(projectRootPath) / expandedPath


class KurlySmokeAppConfig(BaseModel):
    """KurlyMarket 상품 수집 smoke 설정."""

    model_config = ConfigDict(extra="ignore")

    product_urls: list[StrictStr] = Field(
        default_factory=lambda: ["""여기에 링크 추가하셈."""],
    )
    timeout_seconds: StrictInt = 60
    scroll_count: StrictInt = 8
    headless: StrictBool = True
    run_ocr_fallback: StrictBool = True
    max_ocr_image_count: StrictInt = 8
    write_summary_artifact: StrictBool = True
    log_full_result: StrictBool = False
    max_logged_notice_options: StrictInt = 3
    max_logged_fields_per_option: StrictInt = 5
    max_logged_ocr_candidate_urls: StrictInt = 5
    field_value_preview_characters: StrictInt = 220
    ocr_text_preview_characters: StrictInt = 500

    @field_validator("product_urls")
    @classmethod
    def NormalizeProductUrls(cls, value: list[StrictStr]) -> list[str]:
        normalizedUrls = [
            item.strip()
            for item in value
            if isinstance(item, str) and item.strip() != ""
        ]
        return normalizedUrls or ["""여기에 링크 추가하셈."""]


class OntologySmokeAppConfig(BaseModel):
    """온톨로지 smoke 설정."""

    model_config = ConfigDict(extra="ignore")

    phase_id: StrictStr = "stage1_classification"
    top_k: StrictInt = 8
    max_result_count: StrictInt = 6
    cn_candidate_top_k: StrictInt = 5
    max_product_smoke_inputs: StrictInt = 2
    write_summary_artifact: StrictBool = True
    run_llm_connection_smoke: StrictBool = False
    text_preview_characters: StrictInt = 700
    validation_issue_preview_count: StrictInt = 3
    resource_check_preview_count: StrictInt = 8
    max_validation_fixture_candidates: StrictInt = 3
    stage1_backtracking_retry_attempt: StrictInt = 0


class AppConfig(BaseModel):
    """비밀값이 아닌 프로젝트 실행 설정."""

    model_config = ConfigDict(extra="ignore")

    llm: LlmAppConfig = Field(default_factory=LlmAppConfig)
    paths: AppPathsConfig = Field(default_factory=AppPathsConfig)
    kurly_smoke: KurlySmokeAppConfig = Field(default_factory=KurlySmokeAppConfig)
    ontology_smoke: OntologySmokeAppConfig = Field(
        default_factory=OntologySmokeAppConfig,
    )


def LoadAppConfig(
    projectRootPath: str | Path,
    configPath: Optional[str | Path] = None,
) -> AppConfig:
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
        return AppConfig()
    if tomllib is None:
        raise RuntimeError("Python 3.11+ tomllib is required to read .appconfig.")

    with resolvedConfigPath.open("rb") as configFile:
        configData = tomllib.load(configFile)
    if not isinstance(configData, dict):
        return AppConfig()
    return AppConfig.model_validate(configData)
