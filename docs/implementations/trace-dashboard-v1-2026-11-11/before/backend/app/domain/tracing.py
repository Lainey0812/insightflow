"""Observation contracts. Business records remain the source of analysis truth."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

class TraceModel(BaseModel):
    model_config = ConfigDict(extra='forbid')

class RunManifest(TraceModel):
    schema_version: Literal['workflow-trace-v0.1','workflow-trace-v0.3','workflow-trace-v0.3.1'] = 'workflow-trace-v0.1'
    bindings: dict = Field(default_factory=dict)
    versions: dict = Field(default_factory=dict)
    model_config_snapshot: dict = Field(default_factory=dict)
    source_sha256: dict[str, str] = Field(default_factory=dict)
    capture_scope: str | None = None
    git: dict = Field(default_factory=dict)
    input_sha256: dict[str, str] = Field(default_factory=dict)
    prompt_template_snapshots: dict[str, str] = Field(default_factory=dict)
    raw_content_retained: Literal[False] = False

class TraceRun(TraceModel):
    run_id: str
    kind: Literal['report_generation','workflow'] = 'report_generation'
    session_id: str
    execution_id: str | None = None
    workflow_run_id: str | None = None
    business_revision: int | None = None
    # Observation CAS token, independent of Session revisions and node retries.
    # Legacy JSON rows read as zero; no new table or Attempt entity is required.
    observation_revision: int = Field(default=0, ge=0)
    attempt: int = Field(ge=1)
    retry_of_run_id: str | None = None
    owner_instance: str
    status: Literal['queued','running','waiting_input','waiting_approval','complete','partial','unavailable','failed','interrupted']
    queued_at: str
    started_at: str | None = None
    finished_at: str | None = None
    recovered_at: str | None = None
    duration_ms: float | None = Field(default=None, ge=0)
    report_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    integrity: Literal['observed','incomplete'] = 'observed'
    manifest: RunManifest

    @model_validator(mode='after')
    def valid_kind(self):
        if self.kind == 'report_generation' and not self.execution_id:
            raise ValueError('Report runs require the actual execution ID')
        if self.kind == 'workflow' and (self.execution_id is not None or self.workflow_run_id != self.run_id):
            raise ValueError('Workflow roots refer to themselves and do not invent an execution ID')
        return self

class TraceSpan(TraceModel):
    span_id: str
    run_id: str
    parent_span_id: str | None = None
    name: str
    node_key: str | None = None
    node_attempt: int | None = Field(default=None, ge=1)
    status: Literal['running','complete','partial','failed','skipped','interrupted']
    started_at: str
    finished_at: str | None = None
    recovered_at: str | None = None
    duration_ms: float | None = Field(default=None, ge=0)
    error_code: str | None = None
    error_message: str | None = None
    attributes: dict = Field(default_factory=dict)

class TraceEvent(TraceModel):
    event_id: str
    run_id: str
    span_id: str | None = None
    sequence: int = Field(ge=1)
    event_type: str
    recorded_at: str
    payload: dict = Field(default_factory=dict)

class TraceSnapshot(TraceModel):
    snapshot_id: str
    run_id: str
    span_id: str | None = None
    kind: Literal['evidence','llm_output','report']
    captured_at: str
    content_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    projection: dict = Field(default_factory=dict)
    schema_version: Literal['controlled-projection-v1'] = 'controlled-projection-v1'
    raw_content_retained: Literal[False] = False
