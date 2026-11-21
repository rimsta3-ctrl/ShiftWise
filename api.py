"""Step 4: FastAPI wrapper around the LangGraph agent.

Endpoints
    GET  /health          liveness probe
    GET  /config          model, limits and relaxation order (for the dashboard)
    POST /plan            text request -> final schedule (one JSON response)
    POST /plan/stream     same, but streams every agent step as Server-Sent Events
    POST /solve/stream    structured ScheduleProblem -> streamed run, no LLM extraction
    GET  /evaluation      measured benchmark / evaluation results, if present on disk
"""
import json
import os
import queue
import threading
import time
from pathlib import Path
from typing import Callable, Iterator

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.exceptions import ModelError
from pydantic import BaseModel, Field

from extractor import DEFAULT_MODEL, ExtractionError, build_extractor, extract
from graph import MAX_RELAXATIONS, build_explainer, build_graph, template_explanation
from models import ScheduleProblem, ScheduleResult
from scheduler import DEFAULT_TIME_LIMIT_S, format_schedule
from validator import find_violations, triples_from_result

RESULTS_DIR = Path(__file__).parent / "evaluation" / "results"
LLM_ERRORS = (ModelError, httpx.TimeoutException, TimeoutError)
LOCALHOST_ORIGINS = r"https?://(localhost|127\.0\.0\.1)(:\d+)?"  # any port: the Flutter dev server picks one


def cors_settings() -> dict:
    """Allowed browser origins.

    SHIFTWISE_CORS_ORIGINS="https://a.example,https://b.example" allows exactly those origins.
    Unset or empty: localhost and 127.0.0.1 only, on any port.
    """
    origins = [o.strip().rstrip("/") for o in os.getenv("SHIFTWISE_CORS_ORIGINS", "").split(",") if o.strip()]
    return {"allow_origins": origins} if origins else {"allow_origin_regex": LOCALHOST_ORIGINS}
RELAXATION_ORDER = [
    "Allow one more consecutive working day (up to 6)",
    "Drop the 'no morning after night' rule",
    "Ignore the last listed unavailability",
    "Lower the staffing per shift by one",
]


class PlanRequest(BaseModel):
    request: str = Field(min_length=3, max_length=2000, examples=[
        "8 employees, 3 shifts a day, max 5 days in a row, Sara doesn't work on Monday"
    ])


class SolveRequest(BaseModel):
    problem: ScheduleProblem
    llm_explanation: bool = Field(default=False, description="Narrate with the LLM instead of the template")


class PlanResponse(BaseModel):
    problem: ScheduleProblem
    result: ScheduleResult
    relaxations: list[str]
    schedule_text: str
    explanation: str


def final_payload(out: dict) -> dict:
    """Everything the dashboard needs once the agent is done, including an independent check."""
    problem, result = out["problem"], out["result"]
    template = template_explanation(problem, result, out["relaxations"])
    return {
        "type": "result",
        "original_problem": out["original_problem"].model_dump(mode="json"),
        "problem": problem.model_dump(mode="json"),
        "result": result.model_dump(mode="json"),
        "relaxations": out["relaxations"],
        "explanation": out["explanation"],
        "explanation_source": "template" if out["explanation"] == template else "llm",
        "schedule_text": format_schedule(problem, result),
        "required_shifts": problem.min_staff_per_shift * len(problem.shifts) * problem.num_days,
        "verification": {
            "checked": bool(result.assignments),
            "violations": find_violations(problem, triples_from_result(result)) if result.assignments else [],
        },
    }


def sse_stream(run: Callable[[Callable[[dict], None]], dict]) -> Iterator[str]:
    """Run the agent in a worker thread and relay its events as Server-Sent Events.

    Every event carries t_ms (milliseconds since the request started). Errors after the stream
    has started cannot change the HTTP status, so they are sent as {"type": "error", "status": ...}.
    """
    events: queue.Queue = queue.Queue()
    t0 = time.perf_counter()

    def emit(event: dict) -> None:
        events.put({**event, "t_ms": round((time.perf_counter() - t0) * 1000, 1)})

    def worker() -> None:
        try:
            emit({"type": "start"})
            emit(final_payload(run(emit)))
        except ExtractionError as exc:
            emit({"type": "error", "status": 422, "detail": f"Could not understand the request: {exc}"})
        except LLM_ERRORS as exc:
            emit({"type": "error", "status": 503, "detail": f"The language model is unavailable: {exc}"[:500]})
        except Exception as exc:  # surfaced to the dashboard instead of a silently dropped stream
            emit({"type": "error", "status": 500, "detail": f"{type(exc).__name__}: {exc}"[:500]})
        finally:
            events.put(None)

    threading.Thread(target=worker, daemon=True).start()
    while (event := events.get()) is not None:
        yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


def _event_response(generator: Iterator[str]) -> StreamingResponse:
    return StreamingResponse(generator, media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _read_json(name: str) -> dict | None:
    path = RESULTS_DIR / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def create_app(agent=None, *, extract_fn=None, explain_fn=None) -> FastAPI:
    """Everything LLM-dependent is injectable for tests; otherwise the Gemini pieces are built lazily."""
    app = FastAPI(title="ShiftWise", version="0.3.0")
    app.add_middleware(CORSMiddleware, **cors_settings(), allow_methods=["GET", "POST"], allow_headers=["Content-Type"])
    app.state.agent = agent
    lazy: dict = {}

    def llm_explainer():
        if explain_fn is not None:
            return explain_fn
        if "explainer" not in lazy:
            lazy["explainer"] = build_explainer()
        return lazy["explainer"]

    def llm_extractor(emit: Callable[[dict], None]) -> Callable[[str], ScheduleProblem]:
        if extract_fn is not None:
            return extract_fn
        if "chain" not in lazy:
            lazy["chain"] = build_extractor()
        return lambda text: extract(
            text, chain=lazy["chain"],
            on_attempt=lambda n, error: emit({"type": "extract_attempt", "attempt": n, "error": error}),
        )

    def get_agent():
        if app.state.agent is None:
            app.state.agent = build_graph(extract_fn=extract_fn, explain_fn=llm_explainer())
        return app.state.agent

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/config")
    def config() -> dict:
        return {
            "model": DEFAULT_MODEL,
            "llm_key_configured": bool(os.getenv("GOOGLE_API_KEY")) or extract_fn is not None,
            "solver_time_limit_s": DEFAULT_TIME_LIMIT_S,
            "max_relaxations": MAX_RELAXATIONS,
            "max_extraction_attempts": 3,
            "relaxation_order": RELAXATION_ORDER,
            "defaults": ScheduleProblem(employees=["Employee 1"]).model_dump(mode="json"),
        }

    @app.post("/plan", response_model=PlanResponse)
    def plan(body: PlanRequest) -> PlanResponse:
        try:
            out = get_agent().invoke({"request": body.request})
        except ExtractionError as exc:
            raise HTTPException(status_code=422, detail=f"Could not understand the request: {exc}") from exc
        except LLM_ERRORS as exc:
            # The LLM provider is down, rate-limited or too slow: a retryable condition, not a server bug
            raise HTTPException(status_code=503, detail="The language model is unavailable, please retry later.") from exc
        return PlanResponse(
            problem=out["problem"],
            result=out["result"],
            relaxations=out["relaxations"],
            schedule_text=format_schedule(out["problem"], out["result"]),
            explanation=out["explanation"],
        )

    @app.post("/plan/stream")
    def plan_stream(body: PlanRequest) -> StreamingResponse:
        def run(emit):
            graph = build_graph(extract_fn=llm_extractor(emit), explain_fn=llm_explainer(), on_event=emit)
            return graph.invoke({"request": body.request})

        return _event_response(sse_stream(run))

    @app.post("/solve/stream")
    def solve_stream(body: SolveRequest) -> StreamingResponse:
        def run(emit):
            explain = llm_explainer() if body.llm_explanation else template_explanation
            graph = build_graph(extract_fn=lambda _: body.problem, explain_fn=explain, on_event=emit)
            return graph.invoke({"request": "(structured problem, extraction skipped)"})

        return _event_response(sse_stream(run))

    @app.get("/evaluation")
    def evaluation() -> dict:
        """Measured results written by evaluation/*.py (absent in the Docker image)."""
        cases_path = RESULTS_DIR.parent / "cases.json"
        llm = _read_json("llm_eval")
        runs: dict[str, dict] = {}
        runs_path = RESULTS_DIR / "llm_runs.jsonl"
        if llm and runs_path.exists():
            for line in runs_path.read_text(encoding="utf-8").splitlines():
                rec = json.loads(line) if line.strip() else None
                if rec and rec.get("model") == llm["meta"].get("model"):
                    runs[rec["id"]] = rec  # later lines win
        cases = json.loads(cases_path.read_text(encoding="utf-8"))["cases"] if cases_path.exists() else []
        return {
            "solver_benchmark": _read_json("solver_benchmark"),
            "relaxation_benchmark": _read_json("relaxation_benchmark"),
            "llm_eval": llm,
            "llm_cases": [
                {
                    "id": c["id"], "category": c["category"], "lang": c["lang"], "request": c["request"],
                    "outcome": runs.get(c["id"], {}).get("outcome", "not run"),
                    "exact": runs.get(c["id"], {}).get("score", {}).get("exact"),
                    "relaxations": (len(runs[c["id"]]["relaxations"])
                                    if runs.get(c["id"], {}).get("outcome") == "ok" else None),
                    "baseline_violations": (len(runs[c["id"]]["llm_only"]["violations"])
                                            if "violations" in runs.get(c["id"], {}).get("llm_only", {}) else None),
                    "total_time_s": runs.get(c["id"], {}).get("total_time_s"),
                }
                for c in cases
            ],
        }

    return app


app = create_app()
