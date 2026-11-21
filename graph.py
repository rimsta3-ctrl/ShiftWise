"""Step 3: LangGraph agent  extract -> solve -> (relax -> solve)* -> explain.

                 +---------+      +-------+   feasible    +---------+
   request ----> | extract | ---> | solve | ------------> | explain | ---> END
                 +---------+      +-------+               +---------+
                                    ^   |  infeasible          ^
                                    |   v  and can relax       | nothing left to relax
                                  +-------+                    | (or max attempts)
                                  | relax | -------------------+
                                  +-------+

The LLM only translates (extract) and narrates (explain). The relaxation policy is
deterministic and ordered from least to most harmful, so behaviour is testable and
every concession made to reach a schedule is reported to the user.
"""
import time
from typing import Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from models import ScheduleProblem, ScheduleResult
from scheduler import format_schedule, solve

MAX_RELAXATIONS = 6


class AgentState(TypedDict, total=False):
    request: str
    original_problem: ScheduleProblem  # as extracted, before any relaxation
    problem: ScheduleProblem  # current version, relaxations applied
    result: ScheduleResult
    relaxations: list[str]  # human-readable log of every constraint we loosened
    explanation: str
    error: str


# --------------------------------------------------------------------------- relaxation policy
def relax(problem: ScheduleProblem) -> tuple[ScheduleProblem, str] | None:
    """Loosen ONE constraint, least harmful first. Returns None when nothing is left to loosen."""
    # 1. Allow one more consecutive working day (up to 6, never beyond the 7-day week)
    if problem.max_consecutive_days < min(6, problem.num_days):
        new = problem.max_consecutive_days + 1
        return (
            problem.model_copy(update={"max_consecutive_days": new}),
            f"Allowed up to {new} consecutive working days (was {problem.max_consecutive_days}).",
        )
    # 2. Drop the 'no morning after night' rest rule
    if problem.no_morning_after_night:
        return (
            problem.model_copy(update={"no_morning_after_night": False}),
            "Allowed a morning shift right after a night shift.",
        )
    # 3. Honour one fewer unavailability request (the most recently listed one)
    if problem.unavailable:
        dropped = problem.unavailable[-1]
        return (
            problem.model_copy(update={"unavailable": problem.unavailable[:-1]}),
            f"Ignored the unavailability of {dropped.employee} on day {dropped.day}.",
        )
    # 4. Last resort: lower the minimum staffing per shift
    if problem.min_staff_per_shift > 1:
        new = problem.min_staff_per_shift - 1
        return (
            problem.model_copy(update={"min_staff_per_shift": new}),
            f"Lowered minimum staffing to {new} per shift (was {problem.min_staff_per_shift}).",
        )
    return None


# --------------------------------------------------------------------------- explanation
def template_explanation(problem: ScheduleProblem, result: ScheduleResult, relaxations: list[str]) -> str:
    """Deterministic fallback used when no LLM is available."""
    if result.status == "INFEASIBLE":
        text = (
            "No schedule could be found (INFEASIBLE). "
            "Even after loosening every constraint I was allowed to, the team cannot cover all shifts."
        )
    elif not result.assignments:
        # UNKNOWN = time limit reached without an answer: not a proof that the request is impossible
        text = (
            f"No schedule could be found ({result.status}): the solver reached its time limit "
            "before finding one. This does not prove the request is impossible."
        )
    else:
        text = f"Schedule found ({result.status}); the gap between the most and least loaded employee is {result.shift_gap} shift(s)."
    if relaxations:
        text += "\nTo get there I had to relax:\n" + "\n".join(f"- {r}" for r in relaxations)
    return text


def build_explainer(model: str | None = None) -> Callable[[ScheduleProblem, ScheduleResult, list[str]], str]:
    """LLM explainer (needs GOOGLE_API_KEY). Falls back to the template if the call fails."""
    from langchain_core.prompts import ChatPromptTemplate

    from extractor import build_chat_model  # also loads .env

    chain = (
        ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You explain a workforce schedule to a manager in 3-5 short sentences. "
                    "Use ONLY the facts provided. If constraints were relaxed, say clearly which ones and why. "
                    "Never invent names, shifts or numbers.",
                ),
                ("human", "Schedule:\n{schedule}\n\nRelaxed constraints:\n{relaxations}"),
            ]
        )
        | build_chat_model(model, temperature=0.2)
    )

    def explain(problem: ScheduleProblem, result: ScheduleResult, relaxations: list[str]) -> str:
        try:
            out = chain.invoke(
                {
                    "schedule": format_schedule(problem, result),
                    "relaxations": "\n".join(relaxations) or "none",
                }
            )
            # .text joins the text blocks: recent Gemini models return content as a list of
            # blocks (with thought signatures), so str(out.content) would leak the raw structure
            text = out.text.strip()
        except Exception:  # network, quota, safety filter... never lose the schedule over a narration
            text = ""
        return text or template_explanation(problem, result, relaxations)

    return explain


# --------------------------------------------------------------------------- graph
def build_graph(
    extract_fn: Callable[[str], ScheduleProblem] | None = None,
    explain_fn: Callable[[ScheduleProblem, ScheduleResult, list[str]], str] | None = None,
    solve_fn: Callable[[ScheduleProblem], ScheduleResult] = solve,
    max_relaxations: int = MAX_RELAXATIONS,
    on_event: Callable[[dict], None] | None = None,
):
    """Compile the agent. All LLM-dependent pieces are injectable so tests need no API key.

    `on_event`, if given, receives a dict for every node start/end and every routing decision,
    which is how the dashboard shows the agent's work live. It never changes the behaviour.
    """
    if extract_fn is None:
        from extractor import extract as extract_fn  # noqa: PLC0415
    explain_fn = explain_fn or template_explanation
    emit = on_event or (lambda event: None)

    def traced(name: str, fn: Callable[[AgentState], AgentState], details: Callable[[AgentState, AgentState], dict]):
        def node(state: AgentState) -> AgentState:
            emit({"type": "node_start", "node": name, "iteration": len(state.get("relaxations", []))})
            t0 = time.perf_counter()
            update = fn(state)
            emit({"type": "node_end", "node": name, "duration_ms": round((time.perf_counter() - t0) * 1000, 1),
                  **details(state, update)})
            return update

        return node

    def extract_node(state: AgentState) -> AgentState:
        problem = extract_fn(state["request"])
        return {"problem": problem, "original_problem": problem, "relaxations": []}

    def solve_node(state: AgentState) -> AgentState:
        return {"result": solve_fn(state["problem"])}

    def relax_node(state: AgentState) -> AgentState:
        new_problem, note = relax(state["problem"])  # route() guarantees this is not None
        return {"problem": new_problem, "relaxations": state["relaxations"] + [note]}

    def explain_node(state: AgentState) -> AgentState:
        return {"explanation": explain_fn(state["problem"], state["result"], state["relaxations"])}

    def decide(state: AgentState) -> tuple[str, str]:
        result = state["result"]
        if result.assignments:  # OPTIMAL or FEASIBLE
            return "explain", f"schedule found ({result.status})"
        # UNKNOWN (timeout) is not proof of infeasibility: relaxing would hide a solver limit
        if result.status != "INFEASIBLE":
            return "explain", f"{result.status}: time limit reached, which does not prove infeasibility"
        if len(state["relaxations"]) >= max_relaxations:
            return "explain", f"INFEASIBLE and the cap of {max_relaxations} relaxations is reached"
        if relax(state["problem"]) is None:
            return "explain", "INFEASIBLE and nothing is left to relax"
        return "relax", "INFEASIBLE: loosen one more constraint and solve again"

    def route(state: AgentState) -> str:
        decision, reason = decide(state)
        emit({"type": "route", "decision": decision, "reason": reason})
        return decision

    g = StateGraph(AgentState)
    g.add_node("extract", traced("extract", extract_node, lambda s, u: {"problem": u["problem"].model_dump()}))
    g.add_node("solve", traced("solve", solve_node, lambda s, u: {
        "status": u["result"].status,
        "solve_time_s": round(u["result"].solve_time_s, 4),
        "shift_gap": u["result"].shift_gap,
        "assigned_shifts": sum(len(days) for days in u["result"].assignments.values()),
    }))
    g.add_node("relax", traced("relax", relax_node, lambda s, u: {
        "note": u["relaxations"][-1], "problem": u["problem"].model_dump(),
    }))
    g.add_node("explain", traced("explain", explain_node, lambda s, u: {"explanation": u["explanation"]}))
    g.add_edge(START, "extract")
    g.add_edge("extract", "solve")
    g.add_conditional_edges("solve", route, {"relax": "relax", "explain": "explain"})
    g.add_edge("relax", "solve")
    g.add_edge("explain", END)
    return g.compile()


if __name__ == "__main__":
    import sys

    from extractor import EXAMPLE, extract

    text = " ".join(sys.argv[1:]) or EXAMPLE
    app = build_graph(extract_fn=extract, explain_fn=build_explainer())
    out = app.invoke({"request": text})
    print(format_schedule(out["problem"], out["result"]))
    print("\n" + out["explanation"])
