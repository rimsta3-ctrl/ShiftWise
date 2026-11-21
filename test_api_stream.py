"""Streaming endpoints used by the dashboard (Server-Sent Events). Fully offline: LLM parts are injected."""
import json

from fastapi.testclient import TestClient

from api import create_app
from extractor import ExtractionError, extract
from graph import template_explanation
from models import ScheduleProblem

TEAM = ["Sara", "Ali", "Mona", "Yassine", "Leila", "Omar"]


def events(response) -> list[dict]:
    assert response.headers["content-type"].startswith("text/event-stream")
    return [json.loads(chunk.removeprefix("data: ")) for chunk in response.text.split("\n\n") if chunk.strip()]


def test_solve_stream_shows_every_step_of_the_relaxation_loop():
    # 6 people, 2 per shift: infeasible until staffing is lowered (3 relaxations)
    body = {"problem": ScheduleProblem(employees=TEAM, min_staff_per_shift=2).model_dump()}
    ev = events(TestClient(create_app()).post("/solve/stream", json=body))

    assert ev[0]["type"] == "start" and ev[-1]["type"] == "result"
    nodes = [e["node"] for e in ev if e["type"] == "node_end"]
    assert nodes == ["extract", "solve", "relax", "solve", "relax", "solve", "relax", "solve", "explain"]
    decisions = [e["decision"] for e in ev if e["type"] == "route"]
    assert decisions == ["relax", "relax", "relax", "explain"]
    assert all(e["reason"] for e in ev if e["type"] == "route")
    assert [e["status"] for e in ev if e.get("node") == "solve" and e["type"] == "node_end"][-1] == "OPTIMAL"
    assert all(a["t_ms"] <= b["t_ms"] for a, b in zip(ev, ev[1:]))

    result = ev[-1]
    assert len(result["relaxations"]) == 3
    assert result["original_problem"]["min_staff_per_shift"] == 2 and result["problem"]["min_staff_per_shift"] == 1
    assert result["verification"] == {"checked": True, "violations": []}
    assert result["explanation_source"] == "template"
    assigned = sum(len(days) for days in result["result"]["assignments"].values())
    assert assigned == result["required_shifts"] == 21


def test_plan_stream_reports_extraction_failure_as_error_event():
    def boom(_):
        raise ExtractionError("nope")

    app = create_app(extract_fn=boom, explain_fn=template_explanation)
    ev = events(TestClient(app).post("/plan/stream", json={"request": "gibberish"}))
    assert ev[-1]["type"] == "error" and ev[-1]["status"] == 422


def test_plan_stream_with_injected_extractor():
    app = create_app(extract_fn=lambda _: ScheduleProblem(employees=TEAM), explain_fn=template_explanation)
    ev = events(TestClient(app).post("/plan/stream", json={"request": "six people"}))
    assert ev[-1]["type"] == "result" and ev[-1]["relaxations"] == []


def test_config_and_evaluation_endpoints():
    c = TestClient(create_app())
    cfg = c.get("/config").json()
    assert cfg["max_relaxations"] == 6 and len(cfg["relaxation_order"]) == 4
    assert cfg["defaults"]["num_days"] == 7
    body = c.get("/evaluation").json()
    assert {"solver_benchmark", "relaxation_benchmark", "llm_eval", "llm_cases"} <= body.keys()


def _allowed(app, origin: str) -> bool:
    r = TestClient(app).options("/config", headers={"Origin": origin, "Access-Control-Request-Method": "GET"})
    return r.headers.get("access-control-allow-origin") == origin


def test_cors_default_is_localhost_only(monkeypatch):
    monkeypatch.delenv("SHIFTWISE_CORS_ORIGINS", raising=False)
    app = create_app()
    assert _allowed(app, "http://localhost:53211") and _allowed(app, "http://127.0.0.1:8080")
    assert not _allowed(app, "https://evil.example")


def test_cors_origins_from_environment(monkeypatch):
    monkeypatch.setenv("SHIFTWISE_CORS_ORIGINS", "https://shiftwise.example, https://demo.example/")
    app = create_app()
    assert _allowed(app, "https://shiftwise.example") and _allowed(app, "https://demo.example")
    assert not _allowed(app, "http://localhost:53211")  # an explicit list replaces the default


def test_extract_reports_each_attempt():
    class Chain:
        outputs = [None, ScheduleProblem(employees=["A"])]

        def invoke(self, _):
            return self.outputs.pop(0)

    seen = []
    extract("x", chain=Chain(), on_attempt=lambda n, err: seen.append((n, err)))
    assert seen[0][0] == 1 and "no structured output" in seen[0][1]
    assert seen[1] == (2, None)
