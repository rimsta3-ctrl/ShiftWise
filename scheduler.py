"""CP-SAT solver for the shift-scheduling problem (step 1, no LLM involved)."""
import time

from ortools.sat.python import cp_model

from models import DAY_NAMES, ScheduleProblem, ScheduleResult


def solve(problem: ScheduleProblem, time_limit_s: float = 10.0) -> ScheduleResult:
    model = cp_model.CpModel()
    E = range(len(problem.employees))
    D = range(problem.num_days)
    S = range(len(problem.shifts))

    # Decision variable: x[e, d, s] = 1 if employee e works shift s on day d
    x = {(e, d, s): model.new_bool_var(f"x_{e}_{d}_{s}") for e in E for d in D for s in S}

    # 1. At most one shift per employee per day
    for e in E:
        for d in D:
            model.add_at_most_one(x[e, d, s] for s in S)

    # 2. Coverage: every shift of every day has enough people
    for d in D:
        for s in S:
            model.add(sum(x[e, d, s] for e in E) >= problem.min_staff_per_shift)

    # 3. Unavailability
    idx = {name: i for i, name in enumerate(problem.employees)}
    for u in problem.unavailable:
        for s in S:
            model.add(x[idx[u.employee], u.day, s] == 0)

    # 4. Max consecutive working days: in any window of k+1 days, at most k worked
    k = problem.max_consecutive_days
    for e in E:
        for start in range(problem.num_days - k):
            model.add(sum(x[e, d, s] for d in range(start, start + k + 1) for s in S) <= k)

    # 5. No morning shift right after a night shift
    if problem.no_morning_after_night and "night" in problem.shifts and "morning" in problem.shifts:
        night, morning = problem.shifts.index("night"), problem.shifts.index("morning")
        for e in E:
            for d in range(problem.num_days - 1):
                model.add(x[e, d, night] + x[e, d + 1, morning] <= 1)

    # Objective: fairness = minimize the gap between the most and least loaded employee
    totals = [sum(x[e, d, s] for d in D for s in S) for e in E]
    hi = model.new_int_var(0, problem.num_days, "hi")
    lo = model.new_int_var(0, problem.num_days, "lo")
    for t in totals:
        model.add(t <= hi)
        model.add(t >= lo)
    model.minimize(hi - lo)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    solver.parameters.num_workers = 8
    t0 = time.perf_counter()
    status = solver.solve(model)
    elapsed = time.perf_counter() - t0

    status_name = solver.status_name(status)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return ScheduleResult(status=status_name, solve_time_s=elapsed)

    assignments: dict[str, dict[int, str]] = {name: {} for name in problem.employees}
    for e in E:
        for d in D:
            for s in S:
                if solver.value(x[e, d, s]):
                    assignments[problem.employees[e]][d] = problem.shifts[s]
    return ScheduleResult(
        status=status_name,
        assignments=assignments,
        shift_gap=int(solver.value(hi) - solver.value(lo)),
        solve_time_s=elapsed,
    )


def format_schedule(problem: ScheduleProblem, result: ScheduleResult) -> str:
    if not result.assignments:
        return f"No schedule ({result.status})."
    days = [DAY_NAMES[d % 7] if problem.num_days <= 7 else f"D{d + 1}" for d in range(problem.num_days)]
    width = max(len(n) for n in problem.employees)
    lines = [" " * width + " | " + " ".join(f"{d:>5}" for d in days)]
    for name in problem.employees:
        cells = [result.assignments[name].get(d, "off")[:5] for d in range(problem.num_days)]
        lines.append(f"{name:<{width}} | " + " ".join(f"{c:>5}" for c in cells))
    lines.append(f"\nstatus={result.status}  shift_gap={result.shift_gap}  time={result.solve_time_s:.3f}s")
    return "\n".join(lines)


if __name__ == "__main__":
    from models import Unavailability

    problem = ScheduleProblem(
        employees=["Sara", "Ali", "Mona", "Yassine", "Leila", "Omar", "Nour", "Karim"],
        min_staff_per_shift=2,
        unavailable=[Unavailability(employee="Sara", day=0)],  # Sara is off on Monday
    )
    print(format_schedule(problem, solve(problem)))
