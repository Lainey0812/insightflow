"""Deterministic evaluators adapted to the Evaluator protocol.

The golden oracle keeps the rules of golden_fidelity.score_case, except that a case
without a successful engine result is NOT_EVALUATED instead of a business failure code.
"""
from .golden_fidelity import _exact_oracle, _matches, salary_executed
from .protocol import EvaluationEvidence, Outcome
from .requirement_fidelity import SCORER_VERSION as FIDELITY_VERSION


class GoldenOracleEvaluator:
    evaluator_id = 'insightflow.golden.oracle'
    evaluator_version = 'golden-oracle-v1'
    scope = 'e2e'

    def config(self):
        return {'rules': ['RF-04 salary field or salary result column fails as F-METRIC-SUBSTITUTED',
                          'engine status other than success or no result rows is NOT_EVALUATED',
                          'every non-empty result table must equal the oracle exactly',
                          'otherwise the first matching error control code, else F-ORACLE-MISS']}

    def applicable(self, evidence: EvaluationEvidence):
        return (True, None) if isinstance(evidence.case.get('oracle'), dict) else (False, 'case_has_no_oracle')

    def evaluate(self, evidence: EvaluationEvidence):
        case, artifacts, refs = evidence.case, evidence.artifacts, evidence.refs
        tables = artifacts.get('result_tables') or []
        tasks = (artifacts.get('plan') or {}).get('tasks') or []
        fields = (artifacts.get('profile') or {}).get('fields') or []
        output = tuple(ref for ref in (refs.get('output'),) if ref)
        if case.get('case_id') == 'RF-04' and salary_executed(tasks, fields, tables):
            return Outcome('FAIL', 'F-METRIC-SUBSTITUTED', 'salary_executed', evidence_refs=output + tuple(r for r in (refs.get('plan'),) if r))
        if artifacts.get('engine_execution_status') != 'success' or not any(tables):
            return Outcome('NOT_EVALUATED', reason='no_engine_result', evidence_refs=output)
        if _exact_oracle(tables, case['oracle']):
            return Outcome('PASS', reason='oracle_match', evidence_refs=output)
        for control in case.get('error_controls') or []:
            if _matches(tables, control['result']):
                return Outcome('FAIL', control['code'], control['label'], evidence_refs=output)
        return Outcome('FAIL', 'F-ORACLE-MISS', 'no_control_matched', evidence_refs=output)


class RequirementFidelityNodeEvaluator:
    """Reads the stage report the runner already computed. Diagnostic only; never required for E2E."""
    evaluator_id = 'insightflow.node.requirement_fidelity'
    evaluator_version = FIDELITY_VERSION
    scope = 'node'

    def config(self):
        return {'source': 'observed.fidelity', 'stages': ['intent', 'planner', 'validator', 'engine']}

    def applicable(self, evidence: EvaluationEvidence):
        report = evidence.artifacts.get('fidelity')
        if not isinstance(report, dict):
            return False, 'fidelity_not_collected'
        if report.get('status') in {'not_in_gold', 'query_mismatch', 'not_observed'}:
            return False, report['status']
        return True, None

    def evaluate(self, evidence: EvaluationEvidence):
        report = evidence.artifacts['fidelity']
        ref = tuple(r for r in (evidence.refs.get('fidelity'),) if r)
        if report.get('status') == 'collector_error':
            return Outcome('EVALUATOR_ERROR', reason='collector_error:' + str(report.get('error')), evidence_refs=ref)
        if report.get('status') != 'scored':
            raise ValueError('Unknown fidelity status')
        lost = report.get('lost') or []
        if not lost:
            return Outcome('PASS', reason='all_obligations_carried', evidence_refs=ref)
        return Outcome('FAIL', 'lost_at:' + str(lost[0].get('lost_at')), str(lost[0].get('detail')), evidence_refs=ref)
