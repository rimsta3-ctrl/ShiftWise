from fastapi.testclient import TestClient

from api import create_app
from extractor import ExtractionError
from graph import build_graph, relax, template_explanation
from models import ScheduleProblem, Unavailability

TEAM = ["Sara", "Ali", "Mona", "Yassine", "Leila", "Omar", "Nour", "Karim"]


def run(problem: ScheduleProblem, **kw):
    agent = build_graph(extract_fn=lambda _: problem, **kw)
    return agent.invoke({"request": "ignored"})


def test_feasible_problem_never_relaxes():
    out = run(ScheduleProblem(employees=TEAM, min_staff_per_shift=2))
    assert out["result"].status in ("OPTIMAL", "FEASIBLE")
    assert out["relaxations"] == []
    assert out["explanation"]


def test_infeasible_problem_is_relaxed_then_solved():
    # 3 people, 3 shifts/day, 1 person each: every day needs all 3, so nobody can ever rest.
    # Only works once max_consecutive_days reaches the 5-day horizon (3 -> 4 -> 5).
    p = ScheduleProblem(employees=["A", "B", "C"], num_days=5, max_consecutive_days=3)
    out = run(p)
    assert out["result"].assignments, "relaxation loop should have found a schedule"
    assert len(out["relaxations"]) >= 1
    assert out["problem"].max_consecutive_days > 3
    assert len(out["relaxations"]) == 2 and "consecutive" in out["relaxations"][0]


def test_gives_up_when_nothing_left_to_relax():
    # 2 people can never cover 3 shifts/day, whatever we relax
    out = run(ScheduleProblem(employees=["A", "B"]))
    assert not out["result"].assignments
    assert out["result"].status == "INFEASIBLE"
    assert "No schedule" in out["explanation"]


def test_max_relaxations_is_respected():
    out = run(ScheduleProblem(employees=["A", "B"]), max_relaxations=2)
    assert len(out["relaxations"]) == 2


def test_unknown_status_does_not_trigger_relaxation():
    from models import ScheduleResult

    out = run(
        ScheduleProblem(employees=TEAM),
        solve_fn=lambda p: ScheduleResult(status="UNKNOWN"),
    )
    assert out["relaxations"] == []


def test_unknown_status_explanation_does_not_claim_infeasibility():
    from models import ScheduleResult

    text = template_explanation(ScheduleProblem(employees=TEAM), ScheduleResult(status="UNKNOWN"), [])
    assert "time limit" in text and "does not prove" in text
    assert "cannot cover" not in text


def test_relax_order_and_exhaustion():
    p = ScheduleProblem(
        employees=["A", "B"], num_days=7, max_consecutive_days=6, min_staff_per_shift=2,
        unavailable=[Unavailability(employee="A", day=0)],
    )
    notes = []
    while (step := relax(p)) is not None:
        p, note = step
        notes.append(note)
    assert "morning shift" in notes[0]
    assert "unavailability" in notes[1]
    assert "minimum staffing" in notes[2]
    assert len(notes) == 3


def test_custom_explainer_receives_relaxations():
    seen = {}

    def explain(problem, result, relaxations):
        seen["r"] = relaxations
        return "custom"

    out = run(ScheduleProblem(employees=["A", "B", "C"], max_consecutive_days=3), explain_fn=explain)
    assert out["explanation"] == "custom"
    assert seen["r"] == out["relaxations"] and seen["r"]


def _fake_llm_explainer(monkeypatch, content):
    """build_explainer with the Gemini chat model replaced by a canned AIMessage."""
    import extractor
    from langchain_core.messages import AIMessage
    from langchain_core.runnables import RunnableLambda

    from graph import build_explainer

    monkeypatch.setattr(extractor, "build_chat_model",
                        lambda model=None, temperature=0.0: RunnableLambda(lambda _: AIMessage(content=content)))
    return build_explainer()


def test_llm_explainer_returns_plain_text_from_content_blocks(monkeypatch):
    # Regression: Gemini 3 returns a list of content blocks; str() leaked "[{'type': 'text', ...}]"
    from scheduler import solve

    blocks = [{"type": "text", "text": "All shifts are covered.", "extras": {"signature": "abc"}}]
    p = ScheduleProblem(employees=TEAM)
    assert _fake_llm_explainer(monkeypatch, blocks)(p, solve(p), []) == "All shifts are covered."


def test_llm_explainer_falls_back_to_template_on_empty_text(monkeypatch):
    from scheduler import solve

    p = ScheduleProblem(employees=TEAM)
    r = solve(p)
    assert _fake_llm_explainer(monkeypatch, "  ")(p, r, []) == template_explanation(p, r, [])


def test_template_explanation_lists_relaxations():
    p = ScheduleProblem(employees=TEAM)
    from scheduler import solve

    text = template_explanation(p, solve(p), ["Allowed up to 6 consecutive working days (was 5)."])
    assert "relax" in text and "6 consecutive" in text


# ---- API
def _client(extract_fn):
    return TestClient(create_app(build_graph(extract_fn=extract_fn)))


def test_api_plan_ok():
    c = _client(lambda _: ScheduleProblem(employees=TEAM, min_staff_per_shift=2))
    r = c.post("/plan", json={"request": "8 employees, 2 per shift"})
    assert r.status_code == 200
    body = r.json()
    assert body["result"]["status"] in ("OPTIMAL", "FEASIBLE")
    assert body["relaxations"] == [] and body["schedule_text"]


def test_api_extraction_failure_is_422():
    def boom(_):
        raise ExtractionError("nope")

    r = _client(boom).post("/plan", json={"request": "gibberish"})
    assert r.status_code == 422


def test_api_llm_outage_is_503():
    from langchain_core.exceptions import ModelError

    def outage(_):
        raise ModelError("503 UNAVAILABLE")

    r = _client(outage).post("/plan", json={"request": "8 employees"})
    assert r.status_code == 503


def test_api_validates_input_and_health():
    c = _client(lambda _: ScheduleProblem(employees=["A"]))
    assert c.post("/plan", json={"request": ""}).status_code == 422
    assert c.get("/health").json() == {"status": "ok"}
