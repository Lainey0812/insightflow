"""Server-owned test approvals; never an HTTP API for clients to grant approval."""
from app.domain.analysis_plan import AnalysisPlan
from app.domain.dataset_profile import DatasetProfile, DatasetRef
from app.domain.enums import SessionStatus
from app.domain.execution import ApprovedExecutionSnapshot, ExecutionRequest
from app.domain.intent import ParsedIntent
from app.domain.models import SessionState, now, uid
from app.planning.validator import PlanValidator
from intent_fixtures import intent_payload
from planning_fixtures import CSV, plan


def upload(client, content=CSV, filename="recruiting.csv", **options):
    response = client.post("/api/v1/datasets", data=options, files={"file": (filename, content)})
    assert response.status_code == 201, response.text
    return DatasetProfile.model_validate(response.json())


def approve(app, profile, tasks=None, intent=None, **approval_options):
    intent = intent or ParsedIntent.model_validate(intent_payload())
    candidate = AnalysisPlan.model_validate(plan(tasks, profile))
    checked = PlanValidator(app.state.capability_registry).validate(candidate, profile)
    checked.intent_snapshot = intent
    approval = ApprovedExecutionSnapshot(approval_id="approval_" + uid(), approved_at=now(),
        validated_plan=checked, intent=intent, **approval_options)
    state = SessionState(title="真实计算集成测试", file=app.state.datasets.file(profile.dataset_id),
        user_goal="比较城市岗位", analysis_mode="goal_driven", status=SessionStatus.APPROVED,
        dataset_ref=DatasetRef(dataset_id=profile.dataset_id, dataset_version=profile.dataset_version),
        profile=profile, current_plan_version=candidate.plan_version, approved_plan_version=candidate.plan_version,
        engine_approval=approval)
    app.state.repository.create(state)
    request = ExecutionRequest(session_id=state.id, plan_id=candidate.plan_id,
        plan_version=candidate.plan_version, execution_request_id="request_" + uid())
    return state, request


def execute(client, request):
    return client.post("/api/v1/executions", json=request.model_dump())
