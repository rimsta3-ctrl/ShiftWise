"""Offline benchmark (no LLM, no API key): CP-SAT vs a greedy baseline, and the relaxation loop.

    python -m evaluation.bench_solver            # both suites, writes evaluation/results/
    python -m evaluation.bench_solver --quick    # 1 seed per config, for a smoke test

Suite "standard": instances in three load bands (share of the team needed every day:
  <=40%, 40-60%, 60-75%). Every CP-SAT schedule is re-checked by validator.find_violations,
  which does not use the CP-SAT model, so "0 violations" is measured rather than assumed.
Suite "tight": over-constrained instances. Those CP-SAT proves INFEASIBLE are sent through
  the LangGraph agent (extraction bypassed) to measure how often relaxation recovers a
  schedule, and whether every concession it made was actually needed.
"""
import argparse
import statistics
from collections import Counter
from itertools import product

from evaluation.baselines import greedy_schedule
from evaluation.common import pct, percentile, run_metadata, write_results
from evaluation.instances import random_problem
from graph import MAX_RELAXATIONS, build_graph, relax
from models import ScheduleProblem
from scheduler import solve
from validator import find_violations, shift_gap, triples_from_result

FOUND = ("OPTIMAL", "FEASIBLE")
SHIFTS_PER_DAY = 3


# --------------------------------------------------------------------------- standard suite
BANDS = (("light", 0.40), ("medium", 0.60), ("heavy", 0.75))  # upper bound of the daily load ratio


def load_band(load: float) -> str:
    return next(name for name, upper in BANDS if load <= upper)


def standard_instances(seeds: int):
    for n, days, staff, seed in product((8, 12, 20, 30, 50), (7, 14, 28), (1, 2, 3, 4, 5, 7, 8, 12), range(seeds)):
        load = SHIFTS_PER_DAY * staff / n  # share of the team needed on any given day
        if load <= BANDS[-1][1]:
            cfg = {"n": n, "days": days, "min_staff": staff, "seed": seed, "load": round(load, 3), "band": load_band(load)}
            yield random_problem(n, days, staff, seed=seed), cfg


def run_standard(seeds: int, time_limit: float) -> tuple[list[dict], dict, str]:
    rows = []
    for problem, cfg in standard_instances(seeds):
        r = solve(problem, time_limit_s=time_limit)
        cp = triples_from_result(r)
        greedy = greedy_schedule(problem)
        g_viol = find_violations(problem, greedy)
        required = problem.min_staff_per_shift * len(problem.shifts) * problem.num_days
        rows.append({
            **cfg,
            "unavailable": len(problem.unavailable),
            "required_shifts": required,
            "cpsat_status": r.status,
            "cpsat_time_s": round(r.solve_time_s, 4),
            "cpsat_gap": r.shift_gap,
            "cpsat_violations": len(find_violations(problem, cp)) if r.assignments else None,
            "cpsat_extra_shifts": len(cp) - required if r.assignments else None,
            "greedy_valid": not g_viol,
            "greedy_understaffed_slots": sum(1 for v in g_viol if "staff <" in v),
            "greedy_other_violations": sum(1 for v in g_viol if "staff <" not in v),
            "greedy_gap": shift_gap(problem, greedy),
        })
        print(f"standard n={cfg['n']:>2} days={cfg['days']:>2} staff={cfg['min_staff']:>2} seed={cfg['seed']} "
              f"({cfg['band']}): {r.status} {r.solve_time_s:.2f}s gap={r.shift_gap} greedy_valid={not g_viol}")

    solved = [r for r in rows if r["cpsat_status"] in FOUND]
    times = [r["cpsat_time_s"] for r in rows]
    both = [r for r in solved if r["greedy_valid"]]
    proven = [r for r in both if r["cpsat_status"] == "OPTIMAL"]  # CP-SAT gap is the true optimum here
    summary = {
        "instances": len(rows),
        "cpsat_status_counts": dict(Counter(r["cpsat_status"] for r in rows)),
        "cpsat_schedules_returned": len(solved),
        "cpsat_total_violations": sum(r["cpsat_violations"] for r in solved),
        "cpsat_total_extra_shifts": sum(r["cpsat_extra_shifts"] for r in solved),
        "cpsat_proven_optimal": sum(r["cpsat_status"] == "OPTIMAL" for r in rows),
        "cpsat_time_median_s": statistics.median(times),
        "cpsat_time_p95_s": percentile(times, 95),
        "cpsat_time_max_s": max(times),
        "cpsat_gap_le_1": sum(r["cpsat_gap"] <= 1 for r in solved),
        "greedy_valid_on_solvable": sum(r["greedy_valid"] for r in solved),
        "greedy_understaffed_slots_total": sum(r["greedy_understaffed_slots"] for r in solved),
        "greedy_gap_mean_when_valid": statistics.mean(r["greedy_gap"] for r in both) if both else None,
        "cpsat_gap_mean_same_instances": statistics.mean(r["cpsat_gap"] for r in both) if both else None,
        "greedy_compared_to_proven_optimum": len(proven),
        "greedy_reaches_optimal_gap": sum(r["greedy_gap"] == r["cpsat_gap"] for r in proven),
        "greedy_max_excess_gap": max((r["greedy_gap"] - r["cpsat_gap"] for r in proven), default=None),
    }

    s = summary
    md = [
        "### Solver benchmark (standard suite)",
        "",
        f"{s['instances']} seeded random instances: 8-50 employees, 7/14/28 days, 3 shifts, 1-12 staff per shift, "
        "10% random unavailability, max 5 consecutive days, no morning after night. "
        f"CP-SAT time limit {time_limit:g} s, 8 workers. Load = share of the team needed every day.",
        "",
        f"- CP-SAT returned a schedule on {pct(len(solved), s['instances'])} instances; statuses "
        f"{s['cpsat_status_counts']} (INFEASIBLE = proven impossible).",
        f"- Independent checker: **{s['cpsat_total_violations']} constraint violations** and "
        f"{s['cpsat_total_extra_shifts']} unrequested shifts in CP-SAT schedules.",
        f"- Fairness optimality proven on {pct(s['cpsat_proven_optimal'], s['instances'])}; "
        f"gap <= 1 shift on {pct(s['cpsat_gap_le_1'], len(solved))} of CP-SAT schedules.",
        f"- Greedy baseline produced a valid schedule on {pct(s['greedy_valid_on_solvable'], len(solved))} of the "
        f"instances CP-SAT solved ({s['greedy_understaffed_slots_total']} under-staffed slots in total). "
        f"On the {len(both)} instances both solved, mean fairness gap: CP-SAT "
        f"{_fmt(s['cpsat_gap_mean_same_instances'])} vs greedy {_fmt(s['greedy_gap_mean_when_valid'])} shifts; "
        f"greedy matched the proven-optimal gap on {pct(s['greedy_reaches_optimal_gap'], s['greedy_compared_to_proven_optimum'])}"
        f" (worst excess: {s['greedy_max_excess_gap']} shifts). Greedy cannot prove a request impossible; "
        "CP-SAT's INFEASIBLE proofs are what trigger the relaxation loop.",
        f"- CP-SAT wall time: median {s['cpsat_time_median_s']:.3f} s, p95 {s['cpsat_time_p95_s']:.3f} s, "
        f"max {s['cpsat_time_max_s']:.3f} s.",
        "",
        "| Load band | Instances | Proven infeasible | CP-SAT valid | Greedy valid | Mean gap CP-SAT / greedy* "
        "| Median / p95 time (s) |",
        "|---|---|---|---|---|---|---|",
    ]
    for band, upper in BANDS:
        g = [r for r in rows if r["band"] == band]
        if not g:
            continue
        gs = [r for r in g if r["cpsat_status"] in FOUND]
        gb = [r for r in gs if r["greedy_valid"]]
        t = [r["cpsat_time_s"] for r in g]
        md.append(
            f"| {band} (<= {upper:.0%}) | {len(g)} | {sum(r['cpsat_status'] == 'INFEASIBLE' for r in g)} "
            f"| {pct(len(gs), len(gs))} | {pct(len(gb), len(gs))} "
            f"| {_fmt(_mean(r['cpsat_gap'] for r in gb))} / {_fmt(_mean(r['greedy_gap'] for r in gb))} "
            f"| {statistics.median(t):.3f} / {percentile(t, 95):.3f} |"
        )
    md += ["", "\\* on instances where both produced a valid schedule. \"Valid\" columns are over the instances "
               "CP-SAT solved (proven-infeasible ones excluded).", "",
           "| Employees | Instances | Median time (s) | p95 time (s) | Max time (s) |", "|---|---|---|---|---|"]
    for n in sorted({r["n"] for r in rows}):
        t = [r["cpsat_time_s"] for r in rows if r["n"] == n]
        md.append(f"| {n} | {len(t)} | {statistics.median(t):.3f} | {percentile(t, 95):.3f} | {max(t):.3f} |")
    return rows, summary, "\n".join(md)


def _mean(values) -> float | None:
    values = list(values)
    return statistics.mean(values) if values else None


# --------------------------------------------------------------------------- tight suite
def tight_instances(seeds: int):
    for n, days, staff, k, p_un, seed in product((5, 6, 8, 10), (7, 14), (1, 2, 3), (3, 4), (0.15, 0.3), range(seeds)):
        if SHIFTS_PER_DAY * staff <= n:  # enough people for at least one day; otherwise the request is absurd
            cfg = {"n": n, "days": days, "min_staff": staff, "max_consecutive": k, "p_unavailable": p_un, "seed": seed}
            yield random_problem(n, days, staff, max_consecutive=k, p_unavailable=p_un, seed=seed), cfg


def concession_kind(note: str) -> str:
    for key, kind in (("consecutive", "consecutive_days"), ("morning", "morning_after_night"),
                      ("unavailability", "unavailability"), ("staffing", "min_staff")):
        if key in note:
            return kind
    return "other"


def avoidable_concessions(original: ScheduleProblem, final: ScheduleProblem, time_limit: float) -> list[str]:
    """Concessions that could be undone (one at a time) while the problem stays feasible.

    A non-empty list proves the agent's relaxation was not minimal. Undo attempts that time
    out count as necessary, so this is a lower bound on non-minimality.
    """
    undo: list[tuple[str, ScheduleProblem]] = []
    if final.max_consecutive_days > original.max_consecutive_days:
        undo.append(("consecutive_days", final.model_copy(update={"max_consecutive_days": final.max_consecutive_days - 1})))
    if original.no_morning_after_night and not final.no_morning_after_night:
        undo.append(("morning_after_night", final.model_copy(update={"no_morning_after_night": True})))
    for u in original.unavailable:
        if u not in final.unavailable:
            undo.append(("unavailability", final.model_copy(update={"unavailable": [*final.unavailable, u]})))
    if final.min_staff_per_shift < original.min_staff_per_shift:
        undo.append(("min_staff", final.model_copy(update={"min_staff_per_shift": final.min_staff_per_shift + 1})))
    return [kind for kind, p in undo if solve(p, time_limit_s=time_limit).status in FOUND]


def run_tight(seeds: int, time_limit: float) -> tuple[list[dict], dict, str]:
    rows = []
    for problem, cfg in tight_instances(seeds):
        first = solve(problem, time_limit_s=time_limit)
        row = {**cfg, "initial_status": first.status}
        if first.status == "INFEASIBLE":
            agent = build_graph(extract_fn=lambda _, p=problem: p, solve_fn=lambda p: solve(p, time_limit_s=time_limit))
            out = agent.invoke({"request": "benchmark"})
            final, result, notes = out["problem"], out["result"], out["relaxations"]
            recovered = bool(result.assignments)
            row.update({
                "recovered": recovered,
                "final_status": result.status,
                "relaxations": [concession_kind(n) for n in notes],
                "stopped_by": "solved" if recovered else ("cap" if len(notes) >= MAX_RELAXATIONS and relax(final) else "exhausted_or_unknown"),
                "final_violations": len(find_violations(final, triples_from_result(result))) if recovered else None,
                "avoidable": avoidable_concessions(problem, final, time_limit) if recovered else None,
            })
        rows.append(row)
        print(f"tight {cfg}: {first.status}" + (f" -> recovered={row['recovered']} relax={row['relaxations']} "
                                                 f"avoidable={row['avoidable']}" if "recovered" in row else ""))

    infeasible = [r for r in rows if r["initial_status"] == "INFEASIBLE"]
    rec = [r for r in infeasible if r["recovered"]]
    n_relax = [len(r["relaxations"]) for r in rec]
    summary = {
        "instances": len(rows),
        "initial_status_counts": dict(Counter(r["initial_status"] for r in rows)),
        "infeasible": len(infeasible),
        "recovered": len(rec),
        "not_recovered_hit_cap": sum(r["stopped_by"] == "cap" for r in infeasible),
        "not_recovered_other": sum(not r["recovered"] and r["stopped_by"] != "cap" for r in infeasible),
        "final_violations_total": sum(r["final_violations"] for r in rec),
        "relaxations_per_recovery": dict(sorted(Counter(n_relax).items())),
        "relaxations_mean": statistics.mean(n_relax) if n_relax else None,
        "concession_kinds_used": dict(Counter(k for r in rec for k in r["relaxations"])),
        "recovered_with_avoidable_concession": sum(bool(r["avoidable"]) for r in rec),
        "avoidable_concessions_total": sum(len(r["avoidable"]) for r in rec),
        "concessions_total": sum(n_relax),
    }

    s = summary
    md = [
        "### Relaxation loop (tight suite)",
        "",
        f"{s['instances']} over-constrained seeded instances (5-10 employees, 7/14 days, max 3-4 consecutive days, "
        f"15-30% unavailability). CP-SAT status before any relaxation: {s['initial_status_counts']}. "
        f"The {s['infeasible']} INFEASIBLE ones were sent through the agent (max {MAX_RELAXATIONS} relaxations).",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Recovered a schedule | {pct(s['recovered'], s['infeasible'])} |",
        f"| Not recovered: stopped at the {MAX_RELAXATIONS}-relaxation cap | {pct(s['not_recovered_hit_cap'], s['infeasible'])} |",
        f"| Not recovered: nothing left to relax, or timeout | {pct(s['not_recovered_other'], s['infeasible'])} |",
        f"| Violations of the relaxed problem in recovered schedules | {s['final_violations_total']} |",
        f"| Mean relaxations per recovery | {_fmt(s['relaxations_mean'])} (distribution {s['relaxations_per_recovery']}) |",
        f"| Recoveries with at least one avoidable concession | {pct(s['recovered_with_avoidable_concession'], s['recovered'])} |",
        f"| Avoidable concessions / all concessions in recoveries | {pct(s['avoidable_concessions_total'], s['concessions_total'])} |",
        "",
        f"Concession types used: {s['concession_kinds_used']}. A concession is *avoidable* when undoing it alone "
        "still leaves a feasible problem, which proves the relaxation was not minimal.",
        "",
        "| Unavailability rate | Max consecutive days | Infeasible instances | Recovered |",
        "|---|---|---|---|",
    ]
    for p_un, k in product(sorted({r["p_unavailable"] for r in rows}), sorted({r["max_consecutive"] for r in rows})):
        g = [r for r in infeasible if r["p_unavailable"] == p_un and r["max_consecutive"] == k]
        md.append(f"| {p_un:.0%} | {k} | {len(g)} | {pct(sum(r['recovered'] for r in g), len(g))} |")
    return rows, summary, "\n".join(md)


def _fmt(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.2f}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--suite", choices=("standard", "tight", "all"), default="all")
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--quick", action="store_true", help="1 seed per config")
    ap.add_argument("--time-limit", type=float, default=10.0, help="CP-SAT limit per solve (s), same as the API")
    args = ap.parse_args()
    seeds = 1 if args.quick else args.seeds

    if args.suite in ("standard", "all"):
        rows, summary, md = run_standard(seeds, args.time_limit)
        write_results("solver_benchmark", {"meta": run_metadata(seeds=seeds, time_limit_s=args.time_limit),
                                           "summary": summary, "rows": rows}, md)
    if args.suite in ("tight", "all"):
        rows, summary, md = run_tight(seeds, args.time_limit)
        write_results("relaxation_benchmark", {"meta": run_metadata(seeds=seeds, time_limit_s=args.time_limit),
                                               "summary": summary, "rows": rows}, md)


if __name__ == "__main__":
    main()
