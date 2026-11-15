"""Classify an agent execution from facts the runner saved. Unknown stays None.

Every result names the facts it used. Order matters: an infrastructure error is not an
agent failure, and a stop at the approval gate is not a crash.
"""
from app.regression.runner import SETTLED
from app.regression.scoring import LLM_UNAVAILABLE_PREFIXES

from .contracts import Derivation


def first_error_node(nodes):
    return next((node.get('name') for node in nodes or [] if node.get('status') == 'error'), None)


def classify(facts: dict, sources: dict) -> dict:
    """facts: runner_error, error_code, engine_status, session_status, lifecycle_status, nodes.
    sources maps each fact name to where it was read. Absent facts must be None, not guessed."""
    runner_error, error_code = facts.get('runner_error'), facts.get('error_code')
    engine, session, lifecycle = facts.get('engine_status'), facts.get('session_status'), facts.get('lifecycle_status')
    failed_node = first_error_node(facts.get('nodes'))

    def result(status, stage, origin, used, basis):
        refs = [sources[name] for name in used if name in sources]
        return {'execution_status': status, 'blocking_stage': stage, 'failure_origin': origin,
                'derivation': Derivation(value=status, sources=refs, basis=basis)}

    if runner_error:
        return result('FAILED', 'evaluation_runner', 'infrastructure', ['runner_error'],
                      'The evaluation runner raised; the agent outcome is not a quality sample.')
    if error_code and error_code.startswith(LLM_UNAVAILABLE_PREFIXES):
        return result('FAILED', failed_node, 'infrastructure', ['error_code', 'nodes'],
                      'Model provider unavailable code; recorded as infrastructure, not agent quality.')
    if engine in {'success', 'partial_success'}:
        return result('COMPLETED', None, None, ['engine_status'], f'Engine execution status {engine}.')
    if engine == 'failed':
        return result('FAILED', 'analysis_engine', 'agent', ['engine_status'], 'Engine execution status failed.')
    if error_code and (session == 'FAILED' or lifecycle == 'failed' or failed_node):
        return result('FAILED', failed_node, 'agent', ['error_code', 'session_status', 'lifecycle_status', 'nodes'],
                      f'Agent error code {error_code}; first error node {failed_node or "not recorded"}.')
    if session == 'AWAITING_APPROVAL' or lifecycle == 'waiting_approval':
        return result('BLOCKED', 'hitl_approval', None, ['session_status', 'lifecycle_status', 'approved_by_runner', 'can_approve'],
                      'The case ended while the plan waited for approval and the runner did not approve it; '
                      'no engine result exists. This is a gate stop, not an agent crash.')
    if session == 'WAITING_FOR_CLARIFICATION' or lifecycle == 'waiting_input':
        return result('BLOCKED', 'clarification', None, ['session_status', 'lifecycle_status'],
                      'The case ended while the agent waited for clarification.')
    if session is not None and session not in SETTLED:
        return result('TIMEOUT', 'runner_wait', None, ['session_status'],
                      'Session status was not settled when the runner wait returned; the wait returns early only on a settled status.')
    return result(None, None, None, [name for name in ('error_code', 'engine_status', 'session_status', 'lifecycle_status') if name in sources],
                  'Saved facts are insufficient to classify this execution.')
