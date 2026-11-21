"""Offline checks of the evaluation harness: labels, scoring and the relaxation-minimality probe."""
import pytest

from evaluation.bench_solver import avoidable_concessions
from evaluation.eval_llm import (
    concrete_expected,
    explanation_mentions,
    gold_status,
    load_cases,
    score_extraction,
)
from models import ScheduleProblem, Unavailability

CASES = load_cases()
BY_ID = {c["id"]: c for c in CASES}


def test_case_ids_are_unique():
    assert len(BY_ID) == len(CASES)


@pytest.mark.parametrize("case", [c for c in CASES if c["expected"] is not None], ids=lambda c: c["id"])
def test_gold_labels_are_valid_and_score_perfectly(case):
    gold = ScheduleProblem(**concrete_expected(case["expected"]))
    score = score_extraction(case, gold)
    assert score["exact"] and not score["invented"]


@pytest.mark.parametrize("case", [c for c in CASES if c["expected"] is not None], ids=lambda c: c["id"])
def test_infeasible_category_matches_the_solver(case):
    assert (gold_status(case) == "INFEASIBLE") == (case["category"] == "infeasible")


def test_scoring_flags_invented_constraints():
    case = BY_ID["distractor-01"]  # preferences only: no unavailability expected
    pred = ScheduleProblem(
        employees=["Sara", "Ali", "Mona", "Yassine", "Leila", "Omar"],
        unavailable=[Unavailability(employee="Ali", day=0)],
    )
    score = score_extraction(case, pred)
    assert not score["exact"]
    assert score["invented"] == ["unavailable Ali day 0"]


def test_scoring_accepts_any_placeholder_names_for_mixed_headcounts():
    case = BY_ID["headcount-03"]  # "8 employees ... Sara doesn't work on Monday"
    pred = ScheduleProblem(employees=["Sara", *[f"Worker {i}" for i in range(7)]],
                           unavailable=[Unavailability(employee="Sara", day=0)])
    assert score_extraction(case, pred)["exact"]


def test_explanation_keyword_check():
    notes = ["Lowered minimum staffing to 1 per shift (was 2)."]
    assert explanation_mentions(notes, "I had to reduce staff to one person per shift.")
    assert not explanation_mentions(notes, "Here is your schedule.")


def test_avoidable_concession_is_detected():
    # Infeasible only because of staffing (6 people, 2 per shift = whole team daily). The agent also
    # loosens the consecutive-day and rest rules first; restoring the rest rule stays feasible.
    original = ScheduleProblem(employees=list("ABCDEF"), min_staff_per_shift=2)
    final = original.model_copy(update={"max_consecutive_days": 6, "no_morning_after_night": False,
                                        "min_staff_per_shift": 1})
    assert "morning_after_night" in avoidable_concessions(original, final, time_limit=10)
