import os
from dataclasses import dataclass, field
from pathlib import Path


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
    intent_max_attempts: int = 2
    intent_enable_thinking: bool | None = None
    planner_max_attempts: int = 2
    planner_enable_thinking: bool | None = None
    report_enable_thinking: bool | None = False
    admin_read_token: str = field(default='', repr=False)
    trace_enabled: bool = True
    admin_snapshot_token: str = field(default='', repr=False)
    admin_local_test_mode: bool = False
    llm_request_retention_days: int | None = None

    def __post_init__(self):
        if self.llm_request_retention_days is not None and (type(self.llm_request_retention_days) is not int or self.llm_request_retention_days < 1):
            raise ValueError('LLM request retention days must be a positive integer or None')

    @classmethod
    def from_env(cls) -> "Settings":
        default = Path(__file__).resolve().parents[3] / "var"
        return cls(Path(os.getenv("INSIGHTFLOW_DATA_DIR", str(default))).resolve(),
                   llm_base_url=os.getenv("INSIGHTFLOW_LLM_BASE_URL", ""),
                   llm_model=os.getenv("INSIGHTFLOW_LLM_MODEL", ""),
                   llm_api_key=os.getenv("INSIGHTFLOW_LLM_API_KEY", ""),
                   llm_timeout_seconds=float(os.getenv("INSIGHTFLOW_LLM_TIMEOUT_SECONDS", "30")),
                   intent_max_attempts=int(os.getenv("INSIGHTFLOW_INTENT_MAX_ATTEMPTS", "2")),
                   intent_enable_thinking=optional_bool("INSIGHTFLOW_INTENT_ENABLE_THINKING"),
                   planner_max_attempts=int(os.getenv("INSIGHTFLOW_PLANNER_MAX_ATTEMPTS", "2")),
                   planner_enable_thinking=optional_bool("INSIGHTFLOW_PLANNER_ENABLE_THINKING"),
                   report_enable_thinking=optional_bool("INSIGHTFLOW_REPORT_ENABLE_THINKING") if os.getenv("INSIGHTFLOW_REPORT_ENABLE_THINKING") else False,
                   admin_read_token=os.getenv('INSIGHTFLOW_ADMIN_READ_TOKEN',''),
                   trace_enabled=optional_bool('INSIGHTFLOW_TRACE_ENABLED') is not False,
                   admin_snapshot_token=os.getenv('INSIGHTFLOW_ADMIN_SNAPSHOT_TOKEN',''),
                   admin_local_test_mode=optional_bool('INSIGHTFLOW_ADMIN_LOCAL_TEST_MODE') is True,
                   llm_request_retention_days=int(os.environ['INSIGHTFLOW_LLM_REQUEST_RETENTION_DAYS']) if os.getenv('INSIGHTFLOW_LLM_REQUEST_RETENTION_DAYS') else None)
