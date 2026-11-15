"""Run metrics as pure functions. A zero denominator yields None, never 100%.

Cases that never started are counted separately and stay out of every denominator.
Infrastructure errors are not valid samples of agent quality.
"""
from collections import Counter

from .contracts import CaseExecution, E2ESummary, EvaluatorResult, TERMINAL_STATUSES


def ratio(numerator: int, denominator: int):
    return None if denominator == 0 else numerator / denominator


def compute(executions: list[CaseExecution], summaries: list[E2ESummary], results: list[EvaluatorResult], *,
            not_started: int = 0, oracle_evaluator_id: str | None = None) -> dict:
    e2e = Counter(s.verdict for s in summaries)
    valid = sum(n for verdict, n in e2e.items() if verdict != 'INFRA_ERROR')
    decided = e2e['PASS'] + e2e['FAIL']
    agent = [e for e in executions if e.failure_origin != 'infrastructure']
    known = [e for e in agent if e.execution_status in TERMINAL_STATUSES]
    status = Counter(e.execution_status for e in known)
    completed = {e.locator for e in known if e.execution_status == 'COMPLETED'}
    oracle = Counter(r.verdict for r in results if r.evaluator_id == oracle_evaluator_id and r.case_execution_ref in completed)
    per_evaluator = {}
    for evaluator_id in sorted({r.evaluator_id for r in results}):
        verdicts = Counter(r.verdict for r in results if r.evaluator_id == evaluator_id)
        total = sum(verdicts.values())
        per_evaluator[evaluator_id] = {'counts': dict(verdicts), 'error_rate': ratio(verdicts['EVALUATOR_ERROR'], total),
                                       'not_evaluated_rate': ratio(verdicts['NOT_EVALUATED'], total),
                                       'pass_rate_when_decided': ratio(verdicts['PASS'], verdicts['PASS'] + verdicts['FAIL'])}
    return {
        'counts': {'started': len(summaries), 'not_started': not_started, 'valid': valid,
                   'infra_error': e2e['INFRA_ERROR'], 'e2e': dict(e2e), 'execution': dict(status),
                   'execution_status_unknown': len(agent) - len(known)},
        'e2e_confirmed_success_rate': ratio(e2e['PASS'], valid),
        'decidable_pass_rate': ratio(e2e['PASS'], decided),
        'evaluation_coverage': ratio(decided, valid),
        'execution_completion_rate': ratio(status['COMPLETED'], len(known)),
        'executed_result_correct_rate': ratio(oracle['PASS'], oracle['PASS'] + oracle['FAIL']),
        'block_rate': ratio(status['BLOCKED'], len(known)),
        'run_failure_rate': ratio(status['FAILED'] + status['TIMEOUT'], len(known)),
        'evaluators': per_evaluator,
    }
