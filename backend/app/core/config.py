import os
from dataclasses import dataclass, field
from pathlib import Path


def configured_number(name: str, default, kind):
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = kind(raw)
    except ValueError:
        raise ValueError(f'{name} must be a {kind.__name__}') from None
    if isinstance(value, bool) or (kind is int and type(value) is not int):
        raise ValueError(f'{name} must be a {kind.__name__}')
    return value


def optional_bool(name: str) -> bool | None:
    value = os.getenv(name, "").strip().lower()
    if not value:
        return None
    if value in {"true", "1"}:
        return True
    if value in {"false", "0"}:
        return False
    raise ValueError(f"{name} must be true or false")


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    max_upload_bytes: int = 10 * 1024 * 1024
    llm_base_url: str = ""
    llm_model: str = ""
    llm_api_key: str = field(default="", repr=False)
    llm_timeout_seconds: float = 30
    llm_temperature: float = 0.7
    llm_top_p: float = 0.8
    llm_max_tokens: int = 8192
    llm_input_usd_per_million: float | None = None
    llm_output_usd_per_million: float | None = None
    intent_max_attempts: int = 2
    intent_enable_thinking: bool | None = None
    planner_max_attempts: int = 2
    planner_enable_thinking: bool | None = None
    report_enable_thinking: bool | None = False
    admin_read_token: str = field(default='', repr=False)
    trace_enabled: bool = True
    admin_snapshot_token: str = field(default='', repr=False)
    admin_local_test_mode: bool = False
    admin_annotation_token: str = field(default='', repr=False)
    llm_request_retention_days: int | None = None
    # None means discovery is not configured. from_env fills the repository defaults.
    # Direct Settings(...) used by tests stays unset and does not scan historical runs.
    evaluation_golden_runs: Path | None = None
    evaluation_tc_runs: Path | None = None
    evaluation_golden_dataset: Path | None = None
    evaluation_tc_dataset: Path | None = None

    def __post_init__(self):
        if self.llm_request_retention_days is not None and (type(self.llm_request_retention_days) is not int or self.llm_request_retention_days < 1):
            raise ValueError('LLM request retention days must be a positive integer or None')
        if isinstance(self.llm_temperature, bool) or not isinstance(self.llm_temperature, (int, float)) or not 0 <= float(self.llm_temperature) <= 2:
            raise ValueError('LLM temperature must be between 0 and 2')
        if isinstance(self.llm_top_p, bool) or not isinstance(self.llm_top_p, (int, float)) or not 0 <= float(self.llm_top_p) <= 1:
            raise ValueError('LLM top_p must be between 0 and 1')
        if type(self.llm_max_tokens) is not int or self.llm_max_tokens < 1:
            raise ValueError('LLM max_tokens must be a positive integer')
        for name, price in (('input', self.llm_input_usd_per_million), ('output', self.llm_output_usd_per_million)):
            if price is not None and (isinstance(price, bool) or not isinstance(price, (int, float)) or float(price) < 0):
                raise ValueError(f'LLM {name} price must be a non-negative number or unset')

    @classmethod
    def from_env(cls) -> "Settings":
        repo = Path(__file__).resolve().parents[3]
        default = repo / "var"
        data_dir = Path(os.getenv("INSIGHTFLOW_DATA_DIR", str(default))).resolve()

        def configured_path(name: str, fallback: Path) -> Path:
            raw = os.getenv(name)
            return Path(raw).expanduser().resolve() if raw and raw.strip() else fallback

        return cls(data_dir,
                   llm_base_url=os.getenv("INSIGHTFLOW_LLM_BASE_URL", ""),
                   llm_model=os.getenv("INSIGHTFLOW_LLM_MODEL", ""),
                   llm_api_key=os.getenv("INSIGHTFLOW_LLM_API_KEY", ""),
                   llm_timeout_seconds=float(os.getenv("INSIGHTFLOW_LLM_TIMEOUT_SECONDS", "30")),
                   llm_temperature=float(configured_number('INSIGHTFLOW_LLM_TEMPERATURE', 0.7, float)),
                   llm_top_p=float(configured_number('INSIGHTFLOW_LLM_TOP_P', 0.8, float)),
                   llm_max_tokens=configured_number('INSIGHTFLOW_LLM_MAX_TOKENS', 8192, int),
                   llm_input_usd_per_million=configured_number('INSIGHTFLOW_LLM_INPUT_USD_PER_MILLION', None, float),
                   llm_output_usd_per_million=configured_number('INSIGHTFLOW_LLM_OUTPUT_USD_PER_MILLION', None, float),
                   intent_max_attempts=int(os.getenv("INSIGHTFLOW_INTENT_MAX_ATTEMPTS", "2")),
                   intent_enable_thinking=optional_bool("INSIGHTFLOW_INTENT_ENABLE_THINKING"),
                   planner_max_attempts=int(os.getenv("INSIGHTFLOW_PLANNER_MAX_ATTEMPTS", "2")),
                   planner_enable_thinking=optional_bool("INSIGHTFLOW_PLANNER_ENABLE_THINKING"),
                   report_enable_thinking=optional_bool("INSIGHTFLOW_REPORT_ENABLE_THINKING") if os.getenv("INSIGHTFLOW_REPORT_ENABLE_THINKING") else False,
                   admin_read_token=os.getenv('INSIGHTFLOW_ADMIN_READ_TOKEN',''),
                   trace_enabled=optional_bool('INSIGHTFLOW_TRACE_ENABLED') is not False,
                   admin_snapshot_token=os.getenv('INSIGHTFLOW_ADMIN_SNAPSHOT_TOKEN',''),
                   admin_local_test_mode=optional_bool('INSIGHTFLOW_ADMIN_LOCAL_TEST_MODE') is True,
                   admin_annotation_token=os.getenv('INSIGHTFLOW_ADMIN_ANNOTATION_TOKEN',''),
                   llm_request_retention_days=int(os.environ['INSIGHTFLOW_LLM_REQUEST_RETENTION_DAYS']) if os.getenv('INSIGHTFLOW_LLM_REQUEST_RETENTION_DAYS') else None,
                   evaluation_golden_runs=configured_path('INSIGHTFLOW_EVALUATION_GOLDEN_RUNS', repo / 'docs/evaluations/requirement-fidelity-golden-v1-2026-11-12/runs'),
                   evaluation_tc_runs=configured_path('INSIGHTFLOW_EVALUATION_TC_RUNS', data_dir / 'regression' / 'runs'),
                   evaluation_golden_dataset=configured_path('INSIGHTFLOW_EVALUATION_GOLDEN_DATASET', repo / 'docs/evaluations/requirement-fidelity-golden-v1-2026-11-12/golden-set.json'),
                   evaluation_tc_dataset=configured_path('INSIGHTFLOW_EVALUATION_TC_DATASET', repo / 'docs/testing/typical-suite-v1-2026-11-09/cases.json'))
