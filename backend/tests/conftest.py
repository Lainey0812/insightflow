import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from intent_fixtures import StubProvider


@pytest.fixture
def provider():
    return StubProvider()


@pytest.fixture
def app(tmp_path, provider):
    return create_app(Settings(tmp_path), provider=provider)


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        yield client


def submit(client, goal="分析销售趋势"):
    response = client.post("/api/v1/sessions", data={"goal": goal, "mode": "goal_driven"},
                           files={"file": ("sales.csv", b"not,the,actual,dataset\n1,2,3,4", "text/csv")})
    assert response.status_code == 201, response.text
    return response.json()


def version_body(state):
    return {"expected_revision": state["revision"], "plan_version": state["current_plan_version"]}
