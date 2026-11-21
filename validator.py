"""Independent schedule checker.

Re-checks a schedule against every hard constraint of a ScheduleProblem without touching
the CP-SAT model. The evaluation uses it to verify (rather than assume) that returned
schedules are valid, and to score schedules produced by baselines (greedy, LLM-only).

A schedule is a list of (employee, day, shift) triples, so double bookings can be detected
even when the producer is not the solver.
"""
from collections import Counter, defaultdict
from typing import Iterable

from models import ScheduleProblem, ScheduleResult

Triple = tuple[str, int, str]


def triples_from_result(result: ScheduleResult) -> list[Triple]:
    return [(name, day, shift) for name, days in result.assignments.items() for day, shift in days.items()]


def find_violations(problem: ScheduleProblem, triples: Iterable[Triple]) -> list[str]:
    """Return one human-readable message per violated constraint instance (empty list = valid)."""
    triples = list(triples)
    violations: list[str] = []
    names, shifts = set(problem.employees), set(problem.shifts)

    # 0. Well-formedness: known employee, day inside the horizon, known shift
    for name, day, shift in triples:
        if name not in names:
            violations.append(f"unknown employee {name!r}")
        if not 0 <= day < problem.num_days:
            violations.append(f"day {day} outside the {problem.num_days}-day horizon")
        if shift not in shifts:
            violations.append(f"unknown shift {shift!r}")

    # 1. At most one shift per employee per day
    for (name, day), n in Counter((name, day) for name, day, _ in triples).items():
        if n > 1:
            violations.append(f"{name} has {n} shifts on day {day}")

    worked: dict[str, dict[int, str]] = defaultdict(dict)
    for name, day, shift in triples:
        worked[name][day] = shift

    # 2. Coverage
    staffed = Counter((day, shift) for _, day, shift in set(triples))
    for day in range(problem.num_days):
        for shift in problem.shifts:
            if staffed[day, shift] < problem.min_staff_per_shift:
                violations.append(
                    f"day {day} {shift}: {staffed[day, shift]} staff < {problem.min_staff_per_shift}"
                )

    # 3. Unavailability
    for u in problem.unavailable:
        if u.day in worked[u.employee]:
            violations.append(f"{u.employee} works on day {u.day} but is unavailable")

    # 4. Max consecutive working days
    for name in problem.employees:
        run = 0
        for day in range(problem.num_days):
            run = run + 1 if day in worked[name] else 0
            if run == problem.max_consecutive_days + 1:  # report each over-long streak once
                violations.append(f"{name} works more than {problem.max_consecutive_days} days in a row")

    # 5. No morning right after night
    if problem.no_morning_after_night:
        for name in problem.employees:
            for day in range(problem.num_days - 1):
                if worked[name].get(day) == "night" and worked[name].get(day + 1) == "morning":
                    violations.append(f"{name} works night on day {day} then morning on day {day + 1}")

    return violations


def shift_gap(problem: ScheduleProblem, triples: Iterable[Triple]) -> int:
    """Fairness metric: most-loaded minus least-loaded employee (employees with no shift count as 0)."""
    load = Counter(name for name, _, _ in triples)
    totals = [load[name] for name in problem.employees]
    return max(totals) - min(totals)
