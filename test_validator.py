"""The independent checker must catch every kind of violation, and CP-SAT output must pass it."""
import pytest

from evaluation.baselines import greedy_schedule
from evaluation.instances import random_problem
from models import ScheduleProblem, Unavailability
from scheduler import solve
from validator import find_violations, shift_gap, triples_from_result

FOUR = ["A", "B", "C", "D"]


def full_cover(problem: ScheduleProblem) -> list[tuple[str, int, str]]:
    """A valid schedule for 4 people, 1 per shift, 2 days: A/B/C on day 0, then D/A/B on day 1."""
    return [("A", 0, "morning"), ("B", 0, "afternoon"), ("C", 0, "night"),
            ("D", 1, "morning"), ("A", 1, "afternoon"), ("B", 1, "night")]


def test_valid_schedule_has_no_violation():
    p = ScheduleProblem(employees=FOUR, num_days=2)
    assert find_violations(p, full_cover(p)) == []


@pytest.mark.parametrize(
    ("problem_kw", "edit", "expected"),
    [
        ({}, lambda t: t[:-1], "staff <"),  # night of day 1 left empty
        ({}, lambda t: t + [("A", 0, "night")], "2 shifts on day 0"),
        ({"unavailable": [Unavailability(employee="D", day=1)]}, lambda t: t, "unavailable"),
        ({}, lambda t: [x if x != ("D", 1, "morning") else ("C", 1, "morning") for x in t], "then morning"),
        ({}, lambda t: t + [("Ghost", 0, "morning")], "unknown employee"),
        ({}, lambda t: t + [("D", 0, "brunch")], "unknown shift"),
        ({}, lambda t: t + [("D", 5, "morning")], "outside"),
    ],
)
def test_each_violation_kind_is_detected(problem_kw, edit, expected):
    p = ScheduleProblem(employees=FOUR, num_days=2, **problem_kw)
    violations = find_violations(p, edit(full_cover(p)))
    assert any(expected in v for v in violations), violations


def test_consecutive_days_violation_is_reported_once_per_streak():
    p = ScheduleProblem(employees=["A"], shifts=["day"], num_days=7, max_consecutive_days=2)
    triples = [("A", d, "day") for d in range(7)]
    assert sum("in a row" in v for v in find_violations(p, triples)) == 1


def test_shift_gap_counts_idle_employees():
    p = ScheduleProblem(employees=FOUR, num_days=2)
    assert shift_gap(p, [("A", 0, "morning"), ("A", 1, "morning")]) == 2  # A=2, B=C=D=0


@pytest.mark.parametrize("seed", range(6))
def test_cpsat_schedules_pass_the_independent_checker(seed):
    p = random_problem(n_employees=12, num_days=7, min_staff=2, max_consecutive=4, p_unavailable=0.15, seed=seed)
    r = solve(p)
    assert r.status in ("OPTIMAL", "FEASIBLE")
    triples = triples_from_result(r)
    assert find_violations(p, triples) == []
    assert len(triples) == p.min_staff_per_shift * len(p.shifts) * p.num_days  # no unrequested shifts
    assert shift_gap(p, triples) == r.shift_gap


def test_greedy_baseline_is_checked_by_the_same_validator():
    easy = random_problem(n_employees=20, num_days=7, min_staff=1, seed=0)
    assert find_violations(easy, greedy_schedule(easy)) == []
    impossible = ScheduleProblem(employees=["A", "B"])  # 2 people cannot staff 3 shifts a day
    assert any("staff <" in v for v in find_violations(impossible, greedy_schedule(impossible)))
