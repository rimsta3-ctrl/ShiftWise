"""Baselines the CP-SAT solver is compared against."""
from models import ScheduleProblem
from validator import Triple


def greedy_schedule(problem: ScheduleProblem) -> list[Triple]:
    """What a careful manager with a spreadsheet might do, written as code.

    Day by day, shift by shift, staff each slot with the least-loaded employees who can
    legally take it (available, not already working today, under the consecutive-day limit,
    no morning after a night). It never backtracks, so it can leave a slot under-staffed
    when earlier choices used up the people who were needed later.
    """
    load = {e: 0 for e in problem.employees}
    streak = {e: 0 for e in problem.employees}  # consecutive days worked up to yesterday
    off = {(u.employee, u.day) for u in problem.unavailable}
    yesterday: dict[str, str] = {}
    triples: list[Triple] = []

    for day in range(problem.num_days):
        today: dict[str, str] = {}
        for shift in problem.shifts:
            candidates = [
                e
                for e in problem.employees
                if e not in today
                and (e, day) not in off
                and streak[e] < problem.max_consecutive_days
                and not (problem.no_morning_after_night and shift == "morning" and yesterday.get(e) == "night")
            ]
            candidates.sort(key=lambda e: (load[e], streak[e]))  # stable: ties keep the input order
            for e in candidates[: problem.min_staff_per_shift]:
                today[e] = shift
                load[e] += 1
                triples.append((e, day, shift))
        for e in problem.employees:
            streak[e] = streak[e] + 1 if e in today else 0
        yesterday = today

    return triples
