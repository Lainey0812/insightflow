"""E2E hard gates. No weighted average: the first gate that decides the case wins.

1. INFRA_ERROR      the runner or model provider failed, so the agent was not fairly tried.
2. FAIL             the task condition is unmet: the agent failed, timed out or was cancelled,
                    stopped at a gate the case did not expect, or ran past a gate it should stop at.
3. FAIL             a required evaluator returned FAIL.
4. EVALUATOR_ERROR  a required evaluator raised.
5. NOT_EVALUATED    execution status unknown or not terminal, a required evaluator could not
                    judge, or no required evaluator exists.
6. PASS             the task condition is met and every required evaluator passed.

Optional evaluators are reported but never change the verdict.
"""
from .contracts import CaseExecution, E2ESummary, EvaluatorResult, TERMINAL_STATUSES


def task_condition(execution: CaseExecution) -> tuple[bool | None, str]:
    status = execution.execution_status
    if status is None:
        return None, 'execution_status_unknown'
    if status not in TERMINAL_STATUSES:
        return None, 'execution_not_terminal:' + status
    if execution.expect_blocked:
        return (True, 'expected_block') if status == 'BLOCKED' else (False, 'expected_block_not_observed:' + status)
    return (True, 'completed') if status == 'COMPLETED' else (False, 'task_not_completed:' + status)


def summarize(execution: CaseExecution, results: list[EvaluatorResult]) -> E2ESummary:
    mine = [r for r in results if r.case_execution_ref == execution.locator]
    required = [r for r in mine if r.required]
    optional = [r for r in mine if not r.required]
    met, why = task_condition(execution)

    def done(verdict, gate, reason):
        return E2ESummary(case_execution_ref=execution.locator, case_id=execution.case_id, verdict=verdict, gate=gate,
                          reason=reason, execution_status=execution.execution_status,
                          execution_completed=None if execution.execution_status is None else execution.execution_status == 'COMPLETED',
                          task_condition_met=met, required_verdicts={r.evaluator_id: r.verdict for r in required},
                          optional_verdicts={r.evaluator_id: r.verdict for r in optional}, provenance=execution.provenance)

    if execution.failure_origin == 'infrastructure':
        return done('INFRA_ERROR', 'infrastructure', execution.error_code or execution.blocking_stage or 'infrastructure_failure')
    if met is False:
        return done('FAIL', 'task_condition', why)
    failed = [r for r in required if r.verdict == 'FAIL']
    if failed:
        return done('FAIL', 'required_evaluator', f'{failed[0].evaluator_id}:{failed[0].failure_code or failed[0].reason}')
    errored = [r for r in required if r.verdict == 'EVALUATOR_ERROR']
    if errored:
        return done('EVALUATOR_ERROR', 'required_evaluator', f'{errored[0].evaluator_id}:{errored[0].reason}')
    if met is None:
        return done('NOT_EVALUATED', 'task_condition', why)
    if not required:
        return done('NOT_EVALUATED', 'required_evaluator', 'no_required_evaluator')
    pending = [r for r in required if r.verdict == 'NOT_EVALUATED']
    if pending:
        return done('NOT_EVALUATED', 'required_evaluator', f'{pending[0].evaluator_id}:{pending[0].reason}')
    return done('PASS', 'all_gates', 'task_condition_met_and_required_passed')
