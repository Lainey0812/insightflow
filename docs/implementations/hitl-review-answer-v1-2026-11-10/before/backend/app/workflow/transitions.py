from app.domain.errors import AppError
from app.domain.enums import SessionStatus as S
from app.domain.models import SessionState

ALLOWED = {
    S.CREATED: {S.PREPARING, S.PROFILING, S.FAILED},
    S.PROFILING: {S.PARSING_INTENT, S.FAILED},
    S.PARSING_INTENT: {S.WAITING_FOR_CLARIFICATION, S.PLANNING, S.FAILED},
    S.PLANNING: {S.VALIDATING, S.FAILED},
    S.VALIDATING: {S.AWAITING_APPROVAL, S.FAILED},
    S.PREPARING: {S.WAITING_FOR_CLARIFICATION, S.AWAITING_APPROVAL, S.FAILED},
    S.WAITING_FOR_CLARIFICATION: {S.PREPARING, S.PARSING_INTENT},
    S.AWAITING_APPROVAL: {S.AWAITING_APPROVAL, S.APPROVED},
    S.APPROVED: {S.AWAITING_APPROVAL, S.RUNNING},
    S.RUNNING: {S.COMPLETED, S.FAILED},
    # Existing real HITL may create a fresh immutable version after completion
    # or execution failure. This records that existing rule, not auto-retry.
    S.COMPLETED: {S.AWAITING_APPROVAL},
    S.FAILED: {S.PROFILING, S.PARSING_INTENT, S.PLANNING, S.VALIDATING, S.AWAITING_APPROVAL},
}


def transition(state: SessionState, target: S) -> None:
    if target not in ALLOWED[state.status]:
        raise AppError("INVALID_TRANSITION", f"当前状态 {state.status} 不能进入 {target}。")
    state.status = target
