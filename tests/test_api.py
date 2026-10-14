"""The local API refuses other hosts and other websites, and answers unknown ids with 404."""

from fastapi.testclient import TestClient

from server.app import app

local = TestClient(app, base_url="http://127.0.0.1:8000")


def test_unknown_flow_is_404():
    assert local.get("/api/map", params={"flow_id": "no-such-flow"}).status_code == 404
    assert local.get("/api/runs", params={"flow_id": "no-such-flow"}).status_code == 404


def test_other_hosts_are_refused():  # DNS rebinding: evil.example resolving to 127.0.0.1
    assert TestClient(app, base_url="http://evil.example").get("/api/flows").status_code == 400


def test_changes_from_other_websites_are_refused():
    assert local.post("/api/chat/stop", headers={"origin": "https://evil.example"}).status_code == 403
    assert local.post("/api/chat/stop", headers={"sec-fetch-site": "cross-site"}).status_code == 403
    assert local.post("/api/chat/stop", headers={"origin": "http://localhost:3000"}).status_code == 403  # other local app
    assert local.post("/api/chat/stop", headers={"origin": "null"}).status_code == 403
    assert local.post("/api/chat/stop", headers={"origin": "http://localhost:5173"}).status_code == 200


def test_csv_export_only_input_or_output():
    assert local.get("/api/runs/x/items.csv", params={"which": "../secrets"}).status_code == 422
