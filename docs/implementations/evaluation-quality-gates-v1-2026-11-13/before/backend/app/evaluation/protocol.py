"""Pluggable evaluator interface. Evaluators see plain mappings, never agent-internal types."""
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol, runtime_checkable

from .contracts import CaseExecution, EvaluatorResult, Scope, Verdict

VERDICTS = frozenset({'PASS', 'FAIL', 'NOT_EVALUATED', 'EVALUATOR_ERROR'})


@dataclass(frozen=True)
class EvaluationEvidence:
    case: Mapping[str, Any]
    execution: CaseExecution
    artifacts: Mapping[str, Any] = field(default_factory=dict)
    refs: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Outcome:
    verdict: Verdict
    failure_code: str | None = None
    reason: str | None = None
    score: float | None = None
    evidence_refs: tuple[str, ...] = ()


@runtime_checkable
class Evaluator(Protocol):
    evaluator_id: str
    evaluator_version: str
    scope: Scope

    def config(self) -> Mapping[str, Any]:
        """Static rule configuration; its hash identifies the rules that produced a verdict."""

    def applicable(self, evidence: EvaluationEvidence) -> tuple[bool, str | None]:
        """False with a reason records NOT_EVALUATED without calling evaluate()."""

    def evaluate(self, evidence: EvaluationEvidence) -> Outcome:
        """Exceptions are recorded as EVALUATOR_ERROR, never as an agent failure."""


def config_hash(evaluator: Evaluator) -> str:
    body = {'evaluator_id': evaluator.evaluator_id, 'evaluator_version': evaluator.evaluator_version,
            'config': evaluator.config()}
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def run_evaluator(evaluator: Evaluator, evidence: EvaluationEvidence, *, required: bool,
                  now: Callable[[], str]) -> EvaluatorResult:
    base = {'evaluator_id': evaluator.evaluator_id, 'evaluator_version': evaluator.evaluator_version,
            'case_execution_ref': evidence.execution.locator, 'evaluation_scope': evaluator.scope,
            'required': required, 'provenance': 'recorded'}
    try:
        base['evaluator_config_hash'] = config_hash(evaluator)
        usable, why = evaluator.applicable(evidence)
        if not usable:
            return EvaluatorResult(**base, verdict='NOT_EVALUATED', reason=why or 'not_applicable', evaluated_at=now())
        outcome = evaluator.evaluate(evidence)
        if not isinstance(outcome, Outcome) or outcome.verdict not in VERDICTS:
            raise TypeError('Evaluator returned an invalid outcome')
    except Exception as exc:
        base.setdefault('evaluator_config_hash', None)
        return EvaluatorResult(**base, verdict='EVALUATOR_ERROR', reason=f'{type(exc).__name__}', evaluated_at=now())
    # A business failure code only describes a FAIL; it cannot ride on an unevaluated result.
    code = outcome.failure_code if outcome.verdict == 'FAIL' else None
    return EvaluatorResult(**base, verdict=outcome.verdict, failure_code=code, reason=outcome.reason,
                           score=outcome.score, evidence_refs=list(outcome.evidence_refs), evaluated_at=now())
