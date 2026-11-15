"""Manually annotated Bad Cases. The annotation is human judgement; the frozen evidence is what was observed."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

BadCaseCategory = Literal['understanding', 'planning', 'calculation', 'insight', 'report', 'failure', 'other']
BadCaseSeverity = Literal['low', 'medium', 'high']
BadCaseStatus = Literal['open', 'confirmed', 'fixed', 'wont_fix', 'invalid', 'in_progress', 'pending_verification']


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class BadCaseCreate(Strict):
    workflow_id: str = Field(min_length=1, max_length=120)
    span_id: str | None = Field(default=None, min_length=1, max_length=120)
    category: BadCaseCategory
    severity: BadCaseSeverity
    title: str = Field(min_length=1, max_length=80)
    observed: str = Field(min_length=1, max_length=2000)
    expected: str = Field(default='', max_length=2000)
    annotator: str = Field(min_length=1, max_length=40)


class BadCaseTransition(Strict):
    status: BadCaseStatus
    note: str = Field(default='', max_length=2000)
    annotator: str = Field(min_length=1, max_length=40)
    expected_sequence: int = Field(ge=1)


class BadCaseAttribution(Strict):
    cause: Literal['prompt', 'data', 'capability', 'validation', 'code', 'unknown']
    node_id: Literal['intent_parser', 'analysis_planner', 'insight_generator'] | None = None
    explanation: str = Field(min_length=1, max_length=2000)
    annotator: str = Field(min_length=1, max_length=40)
    expected_sequence: int = Field(ge=1)


class BadCaseRepair(Strict):
    template_snapshot_id: str = Field(min_length=1, max_length=120)
    annotator: str = Field(min_length=1, max_length=40)
    note: str = Field(default='', max_length=2000)
    expected_sequence: int = Field(ge=1)
