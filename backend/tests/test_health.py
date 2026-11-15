def test_health_and_openapi(client):
    health = client.get("/api/v1/health").json()
    assert health["mode"] == "real"
    assert health["capabilities"]["workflow"] == "v1_real_until_execution_result"
    assert client.get("/openapi.json").status_code == 200


def test_validation_errors_use_shared_contract(client):
    response = client.post("/api/v1/sessions", data={"mode": "invalid"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert client.get("/api/v1/sessions/missing").json()["error"]["code"] == "SESSION_NOT_FOUND"
