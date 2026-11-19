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
from typing import Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from models import ScheduleProblem, ScheduleResult
from scheduler import format_schedule, solve

MAX_RELAXATIONS = 6


class AgentState(TypedDict, total=False):
    request: str
    problem: ScheduleProblem
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
    if not result.assignments:
        text = (
            f"No schedule could be found ({result.status}). "
            "Even after loosening every constraint I was allowed to, the team cannot cover all shifts."
        )
    else:
        text = f"Schedule found ({result.status}); the gap between the most and least loaded employee is {result.shift_gap} shift(s)."
    if relaxations:
        text += "\nTo get there I had to relax:\n" + "\n".join(f"- {r}" for r in relaxations)
    return text


def build_explainer(model: str = "gemini-2.5-flash") -> Callable[[ScheduleProblem, ScheduleResult, list[str]], str]:
    """LLM explainer (needs GOOGLE_API_KEY). Falls back to the template if the call fails."""
    from dotenv import load_dotenv
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_google_genai import ChatGoogleGenerativeAI

    load_dotenv()
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
        | ChatGoogleGenerativeAI(model=model, temperature=0.2)
    )

    def explain(problem: ScheduleProblem, result: ScheduleResult, relaxations: list[str]) -> str:
        try:
            out = chain.invoke(
                {
                    "schedule": format_schedule(problem, result),
                    "relaxations": "\n".join(relaxations) or "none",
                }
            )
            return str(out.content)
        except Exception:  # network, quota, safety filter... never lose the schedule over a narration
            return template_explanation(problem, result, relaxations)

    return explain


# --------------------------------------------------------------------------- graph
def build_graph(
    extract_fn: Callable[[str], ScheduleProblem] | None = None,
    explain_fn: Callable[[ScheduleProblem, ScheduleResult, list[str]], str] | None = None,
    solve_fn: Callable[[ScheduleProblem], ScheduleResult] = solve,
    max_relaxations: int = MAX_RELAXATIONS,
):
    """Compile the agent. All LLM-dependent pieces are injectable so tests need no API key."""
    if extract_fn is None:
        from extractor import extract as extract_fn  # noqa: PLC0415
    explain_fn = explain_fn or template_explanation

    def extract_node(state: AgentState) -> AgentState:
        return {"problem": extract_fn(state["request"]), "relaxations": []}

    def solve_node(state: AgentState) -> AgentState:
        return {"result": solve_fn(state["problem"])}

    def relax_node(state: AgentState) -> AgentState:
        new_problem, note = relax(state["problem"])  # route() guarantees this is not None
        return {"problem": new_problem, "relaxations": state["relaxations"] + [note]}

    def explain_node(state: AgentState) -> AgentState:
        return {"explanation": explain_fn(state["problem"], state["result"], state["relaxations"])}

    def route(state: AgentState) -> str:
        if state["result"].assignments:  # OPTIMAL or FEASIBLE
            return "explain"
        # UNKNOWN (timeout) is not proof of infeasibility: relaxing would hide a solver limit
        if state["result"].status != "INFEASIBLE":
            return "explain"
        if len(state["relaxations"]) >= max_relaxations or relax(state["problem"]) is None:
            return "explain"
        return "relax"

    g = StateGraph(AgentState)
    g.add_node("extract", extract_node)
    g.add_node("solve", solve_node)
    g.add_node("relax", relax_node)
    g.add_node("explain", explain_node)
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
