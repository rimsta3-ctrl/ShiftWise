import pytest
from pydantic import ValidationError

from extractor import ExtractionError, extract
from models import ScheduleProblem, Unavailability


class FakeChain:
    """Stands in for the LLM chain: returns or raises the scripted outputs in order."""

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.requests = []

    def invoke(self, inputs):
        self.requests.append(inputs["request"])
        out = self.outputs.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


def _invalid_problem_error() -> ValidationError:
    try:
        ScheduleProblem(employees=["Sara"], unavailable=[Unavailability(employee="Ghost", day=0)])
    except ValidationError as exc:
        return exc


GOOD = ScheduleProblem(employees=["Sara", "Ali"])


def test_returns_result_on_first_try():
    chain = FakeChain([GOOD])
    assert extract("plan a week", chain=chain) == GOOD
    assert len(chain.requests) == 1


def test_retries_and_feeds_error_back():
    chain = FakeChain([_invalid_problem_error(), GOOD])
    assert extract("plan a week", chain=chain) == GOOD
    assert len(chain.requests) == 2
    assert "rejected" in chain.requests[1] and "Ghost" in chain.requests[1]


def test_none_output_counts_as_failure():
    chain = FakeChain([None, GOOD])
    assert extract("plan a week", chain=chain) == GOOD


def test_raises_after_max_attempts():
    chain = FakeChain([_invalid_problem_error()] * 3)
    with pytest.raises(ExtractionError):
        extract("plan a week", chain=chain, max_attempts=3)
    assert len(chain.requests) == 3
