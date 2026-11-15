import asyncio

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.domain.execution import ExecutionResultV1
from app.main import create_app
from app.planning.validator import PlanValidator
from planning_fixtures import CSV
from report_fixtures import ReportProvider, report_case


def request_body(client, app, failed=False):
    response = client.post("/api/v1/datasets", files={"file":("jobs.csv",CSV,"text/csv")})
    assert response.status_code == 201
    ref = {name:response.json()[name] for name in ["dataset_id","dataset_version"]}
    intent, validated, execution, _ = report_case(failures=["A01"] if failed else [])
    raw_plan = validated.plan.model_dump()
    raw_plan.update(ref)
    profile = app.state.datasets.profile(**{"dataset_id":ref["dataset_id"], "version":ref["dataset_version"]})
    validated = PlanValidator(app.state.capability_registry).validate(raw_plan, profile)
    raw = execution.model_dump()
    raw.update(ref)
    execution = ExecutionResultV1.model_validate(raw)
    return {"intent":intent.model_dump(),"validated_plan":validated.model_dump(mode="json"),"execution":execution.model_dump(mode="json")}


def test_generate_read_download_and_restart_without_reanalysis(tmp_path):
    provider = ReportProvider()
    settings = Settings(tmp_path)
    app = create_app(settings, provider)
    with TestClient(app) as client:
        body = request_body(client, app)
        response = client.post("/api/v1/reports", json=body)
        assert response.status_code == 201, response.text
        report = response.json()
        assert report["preview_url"] == f'/reports/{report["report_id"]}'
        assert len(provider.requests) == 1
        read = client.get(f'/api/v1/reports/{report["report_id"]}')
        assert read.json() == report and "content-disposition" not in read.headers
        download = client.get(report["download_url"])
        assert download.status_code == 200 and "attachment" in download.headers["content-disposition"]
        assert "default-src 'none'" in download.headers["content-security-policy"]
        assert "岗位数量" in download.text and "<script" not in download.text
        assert len(provider.requests) == 1
        assert client.get("/api/v1/sessions").json() == []
    with TestClient(create_app(settings)) as restarted:
        assert restarted.get(f'/api/v1/reports/{report["report_id"]}').json() == report
        assert restarted.get("/api/v1/reports/missing").status_code == 404


def test_unavailable_report_no_provider_configuration_needed(tmp_path):
    app = create_app(Settings(tmp_path))
    with TestClient(app) as client:
        body = request_body(client, app, failed=True)
        response = client.post("/api/v1/reports", json=body)
        assert response.status_code == 201, response.text
        assert response.json()["report_status"] == "unavailable" and response.json()["llm"] is None


def test_invalid_input_and_model_failures_do_not_save_successful_report(tmp_path):
    app = create_app(Settings(tmp_path))
    with TestClient(app) as client:
        body = request_body(client, app)
        response = client.post("/api/v1/reports", json=body)
        assert response.status_code == 503 and response.json()["error"]["code"] == "LLM_NOT_CONFIGURED"
        body["execution"]["source"] = "mock"
        response = client.post("/api/v1/reports", json=body)
        assert response.status_code == 422 and response.json()["error"]["code"] == "MOCK_EXECUTION_NOT_REPORTABLE"
        body["execution"]["source"] = "imported"
        body["execution"]["tasks"][0]["result"]["rows"][0]["job_count"] = "invented"
        assert client.post("/api/v1/reports", json=body).status_code == 422
        from contextlib import closing
        with closing(app.state.reports.database.connect()) as conn:
            assert conn.execute("SELECT COUNT(*) FROM analysis_reports").fetchone()[0] == 0


def test_report_node_accepts_contract_and_propagates_provenance():
    from app.nodes.report_v1 import ReportModuleNode, ReportV1Input
    from app.domain.node_contracts import NodeInput
    from app.services.analysis_report import AnalysisReportService
    from app.planning.capabilities import CapabilityRegistry
    intent, plan, execution, profile = report_case()
    node = ReportModuleNode(AnalysisReportService(ReportProvider(), CapabilityRegistry()))
    output = asyncio.run(node.run(NodeInput(session_id="report-test", payload=ReportV1Input(
        intent=intent, validated_plan=plan, execution=execution, profile=profile))))
    assert output.status == "success" and output.data.execution_id == execution.execution_id
    assert output.provenance.source == "mock"


def test_external_api_cannot_claim_internal_engine_provenance(tmp_path):
    provider = ReportProvider()
    app = create_app(Settings(tmp_path), provider)
    with TestClient(app) as client:
        body = request_body(client, app)
        body["execution"]["source"] = "engine"
        response = client.post("/api/v1/reports", json=body)
        assert response.status_code == 422 and response.json()["error"]["code"] == "REPORT_EXTERNAL_SOURCE_REQUIRED"
        assert not provider.requests
