"""Step 4: FastAPI wrapper around the LangGraph agent."""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from extractor import ExtractionError
from graph import build_explainer, build_graph
from models import ScheduleProblem, ScheduleResult
from scheduler import format_schedule


class PlanRequest(BaseModel):
    request: str = Field(min_length=3, max_length=2000, examples=[
        "8 employees, 3 shifts a day, max 5 days in a row, Sara doesn't work on Monday"
    ])


class PlanResponse(BaseModel):
    problem: ScheduleProblem
    result: ScheduleResult
    relaxations: list[str]
    schedule_text: str
    explanation: str


def create_app(agent=None) -> FastAPI:
    """`agent` can be injected for tests; otherwise the real Gemini-backed graph is built lazily."""
    app = FastAPI(title="Workforce scheduling agent", version="0.1.0")
    app.state.agent = agent

    def get_agent():
        if app.state.agent is None:
            app.state.agent = build_graph(explain_fn=build_explainer())
        return app.state.agent

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.post("/plan", response_model=PlanResponse)
    def plan(body: PlanRequest) -> PlanResponse:
        try:
            out = get_agent().invoke({"request": body.request})
        except ExtractionError as exc:
            raise HTTPException(status_code=422, detail=f"Could not understand the request: {exc}") from exc
        return PlanResponse(
            problem=out["problem"],
            result=out["result"],
            relaxations=out["relaxations"],
            schedule_text=format_schedule(out["problem"], out["result"]),
            explanation=out["explanation"],
        )

    return app


app = create_app()
