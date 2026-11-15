"""Call provenance, separate from business Runs and public analysis contracts."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class RegistryModel(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


class PromptTemplateSnapshot(RegistryModel):
    template_snapshot_id: str
    node_id: str
    version: str
    content_hash: str
    system_template: str
    user_composition: dict
    output_schema_definition: dict
    source_files: dict
    source_commit: str | None = None
    source_dirty: bool | None = None
    provenance: Literal['runtime_source_verified', 'admin_debug_draft'] = 'runtime_source_verified'
    created_at: str
    change_summary: str = 'Register loaded instruction bundle; no prompt text changes.'


class LLMRequestSnapshot(RegistryModel):
    request_snapshot_id: str
    template_snapshot_id: str
    messages_hash: str
    schema_hash: str
    request_hash: str
    model_parameters: dict
    client_config: dict = Field(default_factory=dict)
    payload_ref: str
    created_at: str
    expires_at: str | None = None


class LLMCallRecord(RegistryModel):
    call_id: str
    node_id: str
    operation_id: str
    call_sequence: int = Field(ge=1)
    retry_index: int = Field(ge=0)
    retry_reason: str | None = None
    retry_of_call_id: str | None = None
    template_snapshot_id: str
    request_snapshot_id: str
    run_id: str | None = None
    span_id: str | None = None
    status: Literal['running', 'succeeded', 'failed', 'cancelled', 'interrupted']
    outcome_scope: Literal['provider_protocol'] = 'provider_protocol'
    started_at: str
    finished_at: str | None = None
    duration_ms: float | None = Field(default=None, ge=0)
    error_code: str | None = None
    response_hash: str | None = None
    http_status: int | None = None
    endpoint: str | None = None
    usage: dict = Field(default_factory=dict)


class CallBinding(RegistryModel):
    """Internal only. Never accepted by business HTTP endpoints."""
    template: PromptTemplateSnapshot
    operation_id: str
    call_sequence: int = Field(ge=1)
    retry_index: int = Field(ge=0)
    retry_reason: str | None = None
    run_id: str | None = None
    span_id: str | None = None
