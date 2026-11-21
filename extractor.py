"""Step 2: turn a natural-language request into a validated ScheduleProblem.

The LLM only *translates*. Its output must pass the Pydantic schema; if it does
not, the validation error is sent back to the model so it can correct itself.
"""
import os
from typing import Callable

from dotenv import load_dotenv
from langchain_core.prompts import ChatPromptTemplate

from models import ScheduleProblem

load_dotenv()  # reads GOOGLE_API_KEY (and optionally SHIFTWISE_MODEL) from a local .env file

# gemini-2.5-flash was retired for new API keys; override with SHIFTWISE_MODEL if needed
DEFAULT_MODEL = os.getenv("SHIFTWISE_MODEL", "gemini-3.8-flash")
LLM_TIMEOUT_S = 60.0  # per HTTP call; without it a congested API can block a request for minutes
LLM_MAX_RETRIES = 2  # transport-level retries (429/503), on top of our own validation retries


def build_chat_model(model: str | None = None, temperature: float = 0.0):
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(
        model=model or DEFAULT_MODEL,
        temperature=temperature,
        timeout=LLM_TIMEOUT_S,
        max_retries=LLM_MAX_RETRIES,
    )

SYSTEM_PROMPT = """You convert a workforce-scheduling request into a structured ScheduleProblem.

Rules:
- Days are 0-indexed: 0 = Monday, 1 = Tuesday, ..., 6 = Sunday. The default horizon is 7 days.
- "Weekend" means days 5 and 6.
- Use employee names exactly as written. If only a headcount is given (e.g. "8 employees"),
  name them "Employee 1", "Employee 2", ...
- Use the shift names "morning", "afternoon", "night" unless the request defines other shifts.
- min_staff_per_shift is the exact number of people on every shift: "at least 2 per shift",
  "2 people per shift" and "each shift needs 2" all mean 2. Leave it at 1 if the request says nothing.
- Only fill what the request states; leave every other field at its default.
- Set no_morning_after_night to false only if the request explicitly allows it.
- Never invent employees, days off or constraints that are not in the request."""


class ExtractionError(RuntimeError):
    """Raised when the LLM could not produce a valid ScheduleProblem."""


def build_extractor(model: str | None = None, temperature: float = 0.0):
    """LangChain runnable: {"request": str} -> ScheduleProblem (needs GOOGLE_API_KEY)."""
    llm = build_chat_model(model, temperature)
    prompt = ChatPromptTemplate.from_messages([("system", SYSTEM_PROMPT), ("human", "{request}")])
    return prompt | llm.with_structured_output(ScheduleProblem)


def extract(
    request: str,
    chain=None,
    max_attempts: int = 3,
    on_attempt: Callable[[int, str | None], None] | None = None,
) -> ScheduleProblem:
    """Extract a ScheduleProblem, retrying with the validation error as feedback.

    `chain` can be injected (any object with .invoke) so the logic is testable without an API key.
    `on_attempt(n, error)` is called after each attempt (error is None on success).
    """
    chain = chain or build_extractor()
    report = on_attempt or (lambda n, error: None)
    feedback = ""
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            result = chain.invoke({"request": request + feedback})
            if result is None:
                raise ValueError("the model returned no structured output")
            report(attempt, None)
            return result
        except ValueError as exc:  # pydantic ValidationError and OutputParserException both subclass ValueError
            last_error = exc
            report(attempt, str(exc))
            feedback = f"\n\nYour previous answer was rejected with this error: {exc}\nFix it and answer again."

    raise ExtractionError(f"no valid ScheduleProblem after {max_attempts} attempts: {last_error}") from last_error


EXAMPLE = (
    "Plan a week for 6 employees: Sara, Ali, Mona, Yassine, Leila and Omar. "
    "Every shift needs at least 1 person. Nobody works more than 4 days in a row. "
    "Sara can't work on Monday and Tuesday, and Ali is off on Friday."
)

if __name__ == "__main__":
    import sys

    from scheduler import format_schedule, solve

    text = " ".join(sys.argv[1:]) or EXAMPLE
    problem = extract(text)
    print(problem.model_dump_json(indent=2))
    print()
    print(format_schedule(problem, solve(problem)))
