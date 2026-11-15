from enum import StrEnum


class SessionStatus(StrEnum):
    CREATED = "CREATED"
    PREPARING = "PREPARING"
    PROFILING = "PROFILING"
    PARSING_INTENT = "PARSING_INTENT"
    PLANNING = "PLANNING"
    VALIDATING = "VALIDATING"
    WAITING_FOR_CLARIFICATION = "WAITING_FOR_CLARIFICATION"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class AnalysisMode(StrEnum):
    GOAL_DRIVEN = "goal_driven"
    EXPLORATORY = "exploratory"
    UNDETERMINED = "undetermined"


class Operation(StrEnum):
    SUMMARY = "summary"
    TREND = "trend"
    CATEGORY = "category"
    REGION = "region"
