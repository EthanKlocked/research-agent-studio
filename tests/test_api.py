import json
import pytest
from fastapi.testclient import TestClient


def make_app(test_mode=True, **kwargs):
    from backend.api import create_app
    from backend.config import Settings
    return create_app(Settings(test_mode=test_mode, **kwargs))

def test_configuration_gates_validation_and_no_leak():
    with TestClient(make_app(False)) as c:
        config = c.get("/api/config").json()
        assert config["configured"] is False
        assert config["test_mode_available"] is False
        assert c.post("/api/runs", json={"question":"x", "mode":"live"}).status_code == 409
        assert c.post("/api/runs", json={"question":"x", "mode":"test"}).status_code == 403
        for body in [{"question":""}, {"question":"x"*2001}, {"question":"x", "scenario":"unknown"}, {"question":"x", "endpoint":"https://bad"}]:
            assert c.post("/api/runs", json=body).status_code == 422
        assert c.get("/api/runs/nope").status_code == 404
        assert "api_key" not in str(config)

def test_events_terminal_and_snapshot_recovery():
    with TestClient(make_app()) as c:
        r = c.post("/api/runs", json={"question":"Apple Q4 performance risk", "mode":"test", "scenario":"revise"})
        assert r.status_code == 202
        rid = r.json()["run_id"]
        response = c.get(f"/api/runs/{rid}/events?after=0")
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        assert events[-1]["type"] == "terminal"
        assert all("snapshot" in e["data"] for e in events)
        snapshot = c.get(f"/api/runs/{rid}").json()
        assert snapshot == events[-1]["data"]["snapshot"]
        recovered = c.get(f"/api/runs/{rid}/events?after={events[-2]['seq']}")
        assert '"type":"terminal"' in recovered.text
        assert c.get(f"/api/runs/{rid}/events?after={snapshot['last_seq']}").text == ""
        assert set(snapshot) == {"run_id","question","mode","status","stage","iteration","started_at","finished_at","last_seq","interpreted_request","plan","evidence","report","revisions","evaluation","feedback","errors"}

def test_api_cancellation_and_cross_origin_rejection():
    with TestClient(make_app()) as c:
        assert c.post("/api/runs", headers={"origin":"https://evil.example"}, json={"question":"x","mode":"test"}).status_code == 403
        r = c.post("/api/runs", json={"question":"x","mode":"test","scenario":"timeout"}).json()
        assert c.post(f"/api/runs/{r['run_id']}/cancel").json()["status"] == "cancelled"
        assert c.post(f"/api/runs/{r['run_id']}/cancel").json()["status"] == "cancelled"
