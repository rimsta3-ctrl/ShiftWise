import pytest
from pydantic import ValidationError

from models import ScheduleProblem, Unavailability
from scheduler import solve

TEAM = ["Sara", "Ali", "Mona", "Yassine", "Leila", "Omar", "Nour", "Karim"]
OK = ("OPTIMAL", "FEASIBLE")


def test_coverage_is_respected():
    p = ScheduleProblem(employees=TEAM, min_staff_per_shift=2)
    r = solve(p)
    assert r.status in OK
    for d in range(p.num_days):
        for shift in p.shifts:
            staff = [n for n, a in r.assignments.items() if a.get(d) == shift]
            assert len(staff) >= 2


def test_unavailability_is_respected():
    p = ScheduleProblem(
        employees=TEAM, min_staff_per_shift=2,
        unavailable=[Unavailability(employee="Sara", day=0), Unavailability(employee="Sara", day=1)],
    )
    r = solve(p)
    assert r.status in OK
    assert 0 not in r.assignments["Sara"] and 1 not in r.assignments["Sara"]


def test_max_consecutive_days():
    p = ScheduleProblem(employees=TEAM, min_staff_per_shift=2, num_days=10, max_consecutive_days=3)
    r = solve(p)
    assert r.status in OK
    for days in r.assignments.values():
        run = 0
        for d in range(p.num_days):
            run = run + 1 if d in days else 0
            assert run <= 3


def test_no_morning_after_night():
    p = ScheduleProblem(employees=TEAM, min_staff_per_shift=2)
    r = solve(p)
    assert r.status in OK
    for days in r.assignments.values():
        for d in range(p.num_days - 1):
            assert not (days.get(d) == "night" and days.get(d + 1) == "morning")


def test_no_unrequested_shifts():
    # Regression: with ">=" coverage, minimizing the load gap alone assigned 120 shifts here instead of 21
    p = ScheduleProblem(employees=[f"E{i}" for i in range(30)], min_staff_per_shift=1)
    r = solve(p)
    assert r.status == "OPTIMAL"
    assert sum(len(days) for days in r.assignments.values()) == 21
    assert r.shift_gap == 1  # 21 shifts over 30 people: some work 1, some 0


def test_custom_shifts_without_morning_or_night():
    p = ScheduleProblem(employees=TEAM[:5], shifts=["day", "evening"])
    r = solve(p)
    assert r.status in OK
    assert {s for days in r.assignments.values() for s in days.values()} == {"day", "evening"}


def test_infeasible_when_understaffed():
    # 2 people cannot cover 3 shifts per day with 1 person each
    p = ScheduleProblem(employees=["Sara", "Ali"], min_staff_per_shift=1)
    assert solve(p).status == "INFEASIBLE"


def test_schema_rejects_unknown_employee():
    with pytest.raises(ValidationError):
        ScheduleProblem(employees=["Sara"], unavailable=[Unavailability(employee="Ghost", day=0)])
