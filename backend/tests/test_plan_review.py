from conftest import submit, version_body


def test_revision_retains_versions_and_invalidates_approval(client):
    initial = submit(client)
    sid = initial["id"]
    approved = client.post(f"/api/v1/sessions/{sid}/approvals", json=version_body(initial)).json()
    revision = client.post(f"/api/v1/sessions/{sid}/plan-revisions", json={
        **version_body(approved), "instruction": "增加地区对比"
    }).json()
    assert revision["status"] == "AWAITING_APPROVAL"
    assert revision["approved_plan_version"] is None
    assert revision["plans"][0] == initial["plans"][0]
    assert revision["current_plan_version"] == 2
    assert len(revision["plans"][1]["tasks"]) == 4
    assert client.post(f"/api/v1/sessions/{sid}/execute", json=version_body(revision)).status_code == 409
    assert client.post(f"/api/v1/sessions/{sid}/approvals", json={
        "expected_revision": revision["revision"], "plan_version": 1
    }).json()["error"]["code"] == "STALE_PLAN"
    assert client.get(f"/api/v1/sessions/{sid}/plans").json() == revision["plans"]


def test_deletions_are_enforced_in_execution(client):
    state = submit(client)
    sid = state["id"]
    remove_id = state["plans"][0]["tasks"][1]["id"]
    updated = client.post(f"/api/v1/sessions/{sid}/plan-revisions", json={
        **version_body(state), "remove_task_ids": [remove_id]
    }).json()
    assert updated["current_plan_version"] == 2
    approved = client.post(f"/api/v1/sessions/{sid}/approvals", json=version_body(updated)).json()
    done = client.post(f"/api/v1/sessions/{sid}/execute", json=version_body(approved)).json()
    assert len(done["execution_result"]["results"]) == 2
    assert remove_id not in [r["task_id"] for r in done["execution_result"]["results"]]


def test_stale_changes_and_empty_plan_are_rejected(client):
    state = submit(client)
    sid = state["id"]
    tasks = state["plans"][0]["tasks"]
    assert client.post(f"/api/v1/sessions/{sid}/plan-revisions", json={
        **version_body(state), "remove_task_ids": [t["id"] for t in tasks]
    }).json()["error"]["code"] == "EMPTY_PLAN"
    changed = client.post(f"/api/v1/sessions/{sid}/plan-revisions", json={
        **version_body(state), "remove_task_ids": [tasks[0]["id"]]
    })
    assert changed.status_code == 200
    assert client.post(f"/api/v1/sessions/{sid}/approvals", json=version_body(state)).json()["error"]["code"] == "STALE_SESSION"


def test_mock_instruction_limit_is_explicit(client):
    state = submit(client)
    response = client.post(f'/api/v1/sessions/{state["id"]}/plan-revisions', json={
        **version_body(state), "instruction": "预测未来三年的收入"
    })
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "MOCK_INSTRUCTION_UNSUPPORTED"
