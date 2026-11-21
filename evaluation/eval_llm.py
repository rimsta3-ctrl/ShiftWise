"""LLM evaluation on the labelled requests in cases.json (needs GOOGLE_API_KEY).

    python -m evaluation.eval_llm                  # run missing cases, then write the report
    python -m evaluation.eval_llm --report-only    # rebuild the report from cached runs
    python -m evaluation.eval_llm --only basic-01 days-06 --fresh

For every request it measures:
  1. extraction: is the ScheduleProblem valid, exactly right, field by field right, and did
     the model invent a constraint the user never stated? How often did the retry loop help?
  2. end to end: the full LangGraph agent (extract -> solve -> relax -> explain). Schedules are
     re-checked by the independent validator against the extracted problem AND against the
     gold (expected) problem, i.e. against what the user actually meant.
  3. LLM-only baseline: the same model is asked to write the schedule itself; its output is
     checked by the same validator against the gold problem.

Each case is cached in results/llm_runs.jsonl, so an interrupted run (API quota, 503) resumes
where it stopped. Cases that ended with an API error are retried on the next run.
"""
import argparse
import json
import statistics
import time
from pathlib import Path

from pydantic import BaseModel

from evaluation.common import RESULTS_DIR, pct, percentile, run_metadata, write_results
from extractor import DEFAULT_MODEL, ExtractionError, build_chat_model, build_extractor, extract
from graph import build_explainer, build_graph, template_explanation
from models import ScheduleProblem
from scheduler import solve
from validator import find_violations, shift_gap, triples_from_result

CASES_FILE = Path(__file__).parent / "cases.json"
RUNS_FILE = RESULTS_DIR / "llm_runs.jsonl"
FIELDS = ("employees", "num_days", "shifts", "min_staff_per_shift", "max_consecutive_days", "unavailable",
          "no_morning_after_night")
DEFAULTS = ScheduleProblem(employees=["x"])


# --------------------------------------------------------------------------- gold labels and scoring
def load_cases() -> list[dict]:
    return json.loads(CASES_FILE.read_text(encoding="utf-8"))["cases"]


def gold_problem(case: dict, predicted: ScheduleProblem | None = None) -> ScheduleProblem | None:
    """Concrete gold ScheduleProblem. For {count, include} employee specs the placeholder names are
    arbitrary, so the predicted names are used when they satisfy the spec (None otherwise)."""
    expected = case["expected"]
    if expected is None:
        return None
    employees = expected["employees"]
    if isinstance(employees, dict):
        if predicted is None or not _employees_ok(employees, predicted.employees):
            return None
        employees = predicted.employees
    return ScheduleProblem(**{**expected, "employees": employees})


def concrete_expected(expected: dict) -> dict:
    """Turn an {count, include} employee spec into a concrete list: the named people + placeholders."""
    spec = expected["employees"]
    if not isinstance(spec, dict):
        return expected
    placeholders = [f"Employee {i}" for i in range(1, spec["count"] + 1)]
    return {**expected, "employees": spec["include"] + placeholders[: spec["count"] - len(spec["include"])]}


def _employees_ok(spec, predicted: list[str]) -> bool:
    if isinstance(spec, dict):
        return len(predicted) == spec["count"] and set(spec["include"]) <= set(predicted)
    return {e.strip() for e in predicted} == set(spec)


def score_extraction(case: dict, pred: ScheduleProblem) -> dict:
    """Per-field correctness, plus constraints the model invented (stated nowhere in the request)."""
    exp = case["expected"]
    gold = ScheduleProblem(**concrete_expected(exp))
    unav = lambda p: {(u.employee.strip(), u.day) for u in p.unavailable}  # noqa: E731
    shifts = lambda p: {s.strip().lower() for s in p.shifts}  # noqa: E731
    flag_matters = {"morning", "night"} <= shifts(gold)  # the rest rule is a no-op without both shifts

    fields = {
        "employees": _employees_ok(exp["employees"], pred.employees),
        "num_days": pred.num_days == gold.num_days,
        "shifts": shifts(pred) == shifts(gold),
        "min_staff_per_shift": pred.min_staff_per_shift == gold.min_staff_per_shift,
        "max_consecutive_days": pred.max_consecutive_days == gold.max_consecutive_days,
        "unavailable": unav(pred) == unav(gold),
        "no_morning_after_night": pred.no_morning_after_night == gold.no_morning_after_night or not flag_matters,
    }
    invented = [f"unavailable {e} day {d}" for e, d in sorted(unav(pred) - unav(gold))]
    for f in ("num_days", "min_staff_per_shift", "max_consecutive_days"):
        if getattr(gold, f) == getattr(DEFAULTS, f) != getattr(pred, f):
            invented.append(f"{f}={getattr(pred, f)}")
    if shifts(gold) == shifts(DEFAULTS) != shifts(pred):
        invented.append(f"shifts={sorted(shifts(pred))}")
    if gold.no_morning_after_night and not pred.no_morning_after_night and flag_matters:
        invented.append("no_morning_after_night=False")
    extra_people = (
        len(pred.employees) > exp["employees"]["count"] if isinstance(exp["employees"], dict)
        else bool(set(pred.employees) - set(exp["employees"]))
    )
    if extra_people:
        invented.append("extra employees")
    return {"fields": fields, "exact": all(fields.values()), "invented": invented}


def violation_kind(message: str) -> str:
    for key, kind in (("staff <", "coverage"), ("shifts on day", "double_booking"), ("unavailable", "unavailability"),
                      ("in a row", "consecutive_days"), ("then morning", "morning_after_night")):
        if key in message:
            return kind
    return "malformed"  # unknown employee / shift, day outside the horizon


CONCESSION_KEYWORDS = {
    "consecutive": ("consecutive", "in a row", "straight"),
    "morning": ("morning",),
    "unavailability": ("unavailab", "day off", "time off", "ignored", "despite"),
    "staffing": ("staff", "per shift", "coverage", "minimum"),
}


def explanation_mentions(relaxations: list[str], explanation: str) -> bool:
    """Rough check: for each concession, at least one of its keywords appears in the narration."""
    text = explanation.lower()
    for note in relaxations:
        kind = next((k for k in CONCESSION_KEYWORDS if k in note.lower()), None)
        if kind and not any(w in text for w in CONCESSION_KEYWORDS[kind]):
            return False
    return True


# --------------------------------------------------------------------------- LLM-only baseline
class Assignment(BaseModel):
    employee: str
    day: int
    shift: str


class LLMSchedule(BaseModel):
    assignments: list[Assignment]


BASELINE_PROMPT = """You are a workforce scheduling assistant. Write the complete schedule for the request.

Unless the request says otherwise: plan 7 days, day 0 = Monday ... day 6 = Sunday ("weekend" = days 5 and 6);
shifts are "morning", "afternoon", "night"; every shift of every day needs at least 1 person; an employee works
at most one shift per day and at most 5 days in a row; no morning shift right after a night shift.
If only a headcount is given, name the employees "Employee 1", "Employee 2", ...
Respect every unavailability and keep the number of shifts per employee as balanced as possible.
Return one entry per (employee, day, shift) actually worked."""


def llm_only_schedule(request: str, model: str) -> tuple[list[tuple[str, int, str]] | None, float, str | None]:
    from langchain_core.prompts import ChatPromptTemplate

    chain = ChatPromptTemplate.from_messages([("system", BASELINE_PROMPT), ("human", "{request}")]) | build_chat_model(
        model
    ).with_structured_output(LLMSchedule)
    t0 = time.perf_counter()
    try:
        out = chain.invoke({"request": request})
    except ValueError as exc:  # unparsable output: the baseline simply failed to produce a schedule
        return None, time.perf_counter() - t0, f"parse: {exc}"[:300]
    if out is None:
        return None, time.perf_counter() - t0, "no structured output"
    return [(a.employee, a.day, a.shift) for a in out.assignments], time.perf_counter() - t0, None


# --------------------------------------------------------------------------- one case
class CountingChain:
    def __init__(self, chain):
        self.chain, self.calls = chain, 0

    def invoke(self, inputs):
        self.calls += 1
        return self.chain.invoke(inputs)


def run_case(case: dict, model: str, skip_baseline: bool) -> dict:
    rec: dict = {"id": case["id"], "model": model, "date": time.strftime("%Y-%m-%d %H:%M")}
    extract_chain = CountingChain(build_extractor(model))
    llm_explain = build_explainer(model)

    def extract_fn(text: str) -> ScheduleProblem:
        t0 = time.perf_counter()
        try:
            problem = extract(text, chain=extract_chain)
        finally:
            rec["extract_time_s"] = round(time.perf_counter() - t0, 3)
            rec["extract_attempts"] = extract_chain.calls
        rec["extracted"] = problem.model_dump()
        return problem

    def explain_fn(problem, result, relaxations):
        t0 = time.perf_counter()
        text = llm_explain(problem, result, relaxations)
        rec["explain_time_s"] = round(time.perf_counter() - t0, 3)
        rec["explain_fallback"] = text == template_explanation(problem, result, relaxations)
        return text

    t0 = time.perf_counter()
    try:
        out = build_graph(extract_fn=extract_fn, explain_fn=explain_fn).invoke({"request": case["request"]})
        rec["outcome"] = "ok"
    except ExtractionError as exc:
        rec["outcome"], rec["error"] = "rejected", str(exc)[:500]
    except Exception as exc:  # quota, 503, timeout: infrastructure, not model quality -> retried next run
        rec["outcome"], rec["error"] = "api_error", f"{type(exc).__name__}: {exc}"[:500]
        return rec
    rec["total_time_s"] = round(time.perf_counter() - t0, 3)

    if rec["outcome"] == "ok":
        final, result = out["problem"], out["result"]
        triples = triples_from_result(result)
        rec.update({
            "status": result.status,
            "relaxations": out["relaxations"],
            "explanation": out["explanation"],
            "explanation_mentions_concessions": explanation_mentions(out["relaxations"], out["explanation"]),
            "violations_vs_final": len(find_violations(final, triples)) if result.assignments else None,
        })
        if case["expected"] is not None:
            pred = ScheduleProblem(**rec["extracted"])
            rec["score"] = score_extraction(case, pred)
            gold = gold_problem(case, pred)
            if gold is not None and result.assignments:
                rec["violations_vs_gold"] = [violation_kind(v) for v in find_violations(gold, triples)]

    if not skip_baseline and case["expected"] is not None:
        try:
            triples, seconds, error = llm_only_schedule(case["request"], model)
        except Exception as exc:  # infrastructure error: retry the whole case later
            rec["outcome"], rec["error"] = "api_error", f"baseline {type(exc).__name__}: {exc}"[:500]
            return rec
        base = {"time_s": round(seconds, 3), "error": error}
        # placeholder names make a gold check ambiguous for mixed headcount/name requests: skip those
        gold = None if isinstance(case["expected"]["employees"], dict) else gold_problem(case)
        if triples is not None and gold is not None:
            base.update({
                "violations": [violation_kind(v) for v in find_violations(gold, triples)],
                "gap": shift_gap(gold, triples),
                "extra_shifts": len(set(triples)) - gold.min_staff_per_shift * len(gold.shifts) * gold.num_days,
            })
        rec["llm_only"] = base
    return rec


# --------------------------------------------------------------------------- report
def gold_status(case: dict) -> str | None:
    """Solver status of the gold problem (None if the request should be rejected)."""
    if case["expected"] is None:
        return None
    return solve(ScheduleProblem(**concrete_expected(case["expected"]))).status


def build_report(cases: list[dict], runs: dict[str, dict], model: str) -> tuple[dict, str]:
    by_id = {c["id"]: c for c in cases}
    done = [runs[c["id"]] for c in cases if c["id"] in runs and runs[c["id"]]["outcome"] != "api_error"]
    api_errors = [c["id"] for c in cases if c["id"] not in runs or runs[c["id"]]["outcome"] == "api_error"]
    feasible = {c["id"]: gold_status(c) in ("OPTIMAL", "FEASIBLE") for c in cases if c["expected"] is not None}

    plannable = [r for r in done if by_id[r["id"]]["expected"] is not None]
    rejectable = [r for r in done if by_id[r["id"]]["expected"] is None]
    extracted = [r for r in plannable if r["outcome"] == "ok"]
    scored = [r for r in extracted if "score" in r]
    first_try = [r for r in extracted if r["extract_attempts"] == 1]
    rescued = [r for r in extracted if r["extract_attempts"] > 1]
    exact = [r for r in scored if r["score"]["exact"]]
    invented = [r for r in scored if r["score"]["invented"]]

    with_schedule = [r for r in extracted if r.get("violations_vs_final") is not None]
    unrelaxed_gold = [r for r in with_schedule if "violations_vs_gold" in r and not r["relaxations"]]
    gold_clean = [r for r in unrelaxed_gold if not r["violations_vs_gold"]]
    relaxed = [r for r in extracted if r["relaxations"]]
    times = [r["total_time_s"] for r in done if "total_time_s" in r]
    ext_times = [r["extract_time_s"] for r in done if "extract_time_s" in r]

    base = [r for r in done if "violations" in r.get("llm_only", {}) and feasible.get(r["id"])]
    base_attempted = [r for r in done if "llm_only" in r and feasible.get(r["id"])
                      and not isinstance(by_id[r["id"]]["expected"]["employees"], dict)]
    base_valid = [r for r in base if not r["llm_only"]["violations"]]
    base_kinds: dict[str, int] = {}
    for r in base:
        for k in set(r["llm_only"]["violations"]):
            base_kinds[k] = base_kinds.get(k, 0) + 1
    infeasible_ids = [cid for cid, ok in feasible.items() if not ok]
    base_infeasible = [r for r in done if r["id"] in infeasible_ids and "llm_only" in r]
    base_infeasible_silent = [r for r in base_infeasible if r["llm_only"].get("violations")]
    sw_infeasible = [r for r in done if r["id"] in infeasible_ids and r["outcome"] == "ok"]
    # A ShiftWise answer to an infeasible request is "silent" if it returns a schedule that breaks the
    # extracted problem, or returns one without any disclosed relaxation (i.e. extraction dropped a constraint)
    sw_silent = [r for r in sw_infeasible
                 if r.get("violations_vs_final") is not None and (r["violations_vs_final"] or not r["relaxations"])]

    summary = {
        "model": model,
        "cases_total": len(cases),
        "cases_completed": len(done),
        "cases_api_error": api_errors,
        "extraction_valid": len(extracted),
        "extraction_plannable": len(plannable),
        "extraction_first_try": len(first_try),
        "extraction_rescued_by_retry": [r["id"] for r in rescued],
        "extraction_exact": len(exact),
        "extraction_scored": len(scored),
        "extraction_failed": [r["id"] for r in plannable if r["outcome"] != "ok"],
        "field_accuracy": {f: sum(r["score"]["fields"][f] for r in scored) for f in FIELDS},
        "invented_constraint_cases": {r["id"]: r["score"]["invented"] for r in invented},
        "wrong_cases": {r["id"]: [f for f, ok in r["score"]["fields"].items() if not ok] for r in scored
                        if not r["score"]["exact"]},
        "rejected_correctly": [r["id"] for r in rejectable if r["outcome"] == "rejected"],
        "rejectable": len(rejectable),
        "accepted_instead_of_rejected": {r["id"]: r.get("extracted") for r in rejectable if r["outcome"] == "ok"},
        "schedules_returned": len(with_schedule),
        "violations_vs_extracted_total": sum(r["violations_vs_final"] for r in with_schedule),
        "unrelaxed_checked_vs_gold": len(unrelaxed_gold),
        "unrelaxed_clean_vs_gold": len(gold_clean),
        "gold_violation_cases": {r["id"]: r["violations_vs_gold"] for r in unrelaxed_gold if r["violations_vs_gold"]},
        "relaxed_cases": {r["id"]: r["relaxations"] for r in relaxed},
        "relaxed_explanations_mentioning_all": sum(r["explanation_mentions_concessions"] for r in relaxed),
        "explain_fallbacks": sum(bool(r.get("explain_fallback")) for r in extracted),
        "pipeline_time_median_s": statistics.median(times) if times else None,
        "pipeline_time_p95_s": percentile(times, 95),
        "extract_time_median_s": statistics.median(ext_times) if ext_times else None,
        "baseline_attempted": len(base_attempted),
        "baseline_checked": len(base),
        "baseline_valid": len(base_valid),
        "baseline_no_output": [r["id"] for r in base_attempted if "violations" not in r["llm_only"]],
        "baseline_violation_kinds": base_kinds,
        "baseline_mean_violations": statistics.mean(len(r["llm_only"]["violations"]) for r in base) if base else None,
        "baseline_gap_mean_when_valid": statistics.mean(r["llm_only"]["gap"] for r in base_valid) if base_valid else None,
        "infeasible_requests": infeasible_ids,
        "baseline_infeasible_returned_invalid_schedule": len(base_infeasible_silent),
        "baseline_infeasible_attempted": len(base_infeasible),
        "shiftwise_infeasible_outcomes": {r["id"]: ("schedule after " + str(len(r["relaxations"])) + " disclosed relaxation(s)"
                                                    if r.get("violations_vs_final") is not None else "no schedule, reported as such")
                                          for r in sw_infeasible},
    }

    s = summary
    cats = sorted({c["category"] for c in cases if c["expected"] is not None}, key=[c["category"] for c in cases].index)
    md = [
        f"### LLM evaluation ({model})",
        "",
        f"{len(cases)} labelled requests ({sum(c['lang'] == 'fr' for c in cases)} in French), "
        f"{len(plannable) + len(rejectable)} completed"
        + (f"; not completed because of API errors: {', '.join(api_errors)}" if api_errors else "")
        + ". One run per request, so no variance estimate (temperature 0 is requested, but some Gemini "
        "models use fixed sampling and ignore it).",
        "",
        "**Extraction (text -> ScheduleProblem)**",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Valid ScheduleProblem within 3 attempts | {pct(len(extracted), len(plannable))} |",
        f"| Valid on the first attempt | {pct(len(first_try), len(plannable))} |",
        f"| Requests rescued by the validation-feedback retry | {len(rescued)} |",
        f"| Exact match with the gold label (all 7 fields) | {pct(len(exact), len(scored))} |",
        f"| Requests with an invented constraint | {pct(len(invented), len(scored))} |",
        f"| Unplannable requests correctly rejected | {pct(len(s['rejected_correctly']), len(rejectable))} |",
        "",
        "| Field | Accuracy |",
        "|---|---|",
        *[f"| {f} | {pct(s['field_accuracy'][f], len(scored))} |" for f in FIELDS],
        "",
        "| Category | Exact match |",
        "|---|---|",
        *[f"| {cat} | {pct(sum(r['score']['exact'] for r in scored if by_id[r['id']]['category'] == cat), sum(by_id[r['id']]['category'] == cat for r in scored))} |"
          for cat in cats],
        "",
        "**End to end (LangGraph agent)**",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Schedules returned | {pct(len(with_schedule), len(extracted))} of valid extractions |",
        f"| Violations of the extracted problem (independent checker) | {s['violations_vs_extracted_total']} |",
        f"| Schedules without relaxation that also satisfy the gold problem (user intent) "
        f"| {pct(len(gold_clean), len(unrelaxed_gold))} |",
        f"| Requests that triggered relaxation | {len(relaxed)} |",
        f"| ... whose explanation mentions every concession (keyword check) "
        f"| {pct(s['relaxed_explanations_mentioning_all'], len(relaxed))} |",
        f"| Explanations that fell back to the template | {pct(s['explain_fallbacks'], len(extracted))} |",
        f"| Pipeline latency, median / p95 | {_sec(s['pipeline_time_median_s'])} / {_sec(s['pipeline_time_p95_s'])} |",
        "",
        "**LLM-only baseline (the same model writes the schedule itself)**",
        "",
        "| Metric | LLM only | ShiftWise |",
        "|---|---|---|",
        f"| Feasible requests: schedule satisfies every hard constraint of the gold problem "
        f"| {pct(len(base_valid), len(base_attempted))} | {pct(len(gold_clean), len(unrelaxed_gold))} |",
        f"| Infeasible requests: schedule returned that silently breaks constraints "
        f"| {pct(len(base_infeasible_silent), len(base_infeasible))} | {pct(len(sw_silent), len(sw_infeasible))} |",
        "",
        f"LLM-only violation types (requests affected): {base_kinds or 'none'}; "
        f"no usable output on {len(s['baseline_no_output'])} request(s).",
    ]
    if s["wrong_cases"]:
        md += ["", "Extraction errors: " + "; ".join(f"{k}: {', '.join(v)}" for k, v in s["wrong_cases"].items())]
    if s["invented_constraint_cases"]:
        md += ["", "Invented constraints: " + "; ".join(f"{k}: {', '.join(v)}" for k, v in s["invented_constraint_cases"].items())]
    if s["accepted_instead_of_rejected"]:
        md += ["", "Accepted although it should have been rejected: " + ", ".join(s["accepted_instead_of_rejected"])]
    return summary, "\n".join(md)


def _sec(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.1f} s"


# --------------------------------------------------------------------------- main
def load_runs() -> dict[str, dict]:
    if not RUNS_FILE.exists():
        return {}
    runs = {}
    for line in RUNS_FILE.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            runs[rec["id"]] = rec  # later lines win
    return runs


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--only", nargs="*", help="case ids to run")
    ap.add_argument("--fresh", action="store_true", help="ignore cached runs for the selected cases")
    ap.add_argument("--report-only", action="store_true")
    ap.add_argument("--skip-baseline", action="store_true")
    ap.add_argument("--pause", type=float, default=2.0, help="seconds between cases (rate limits)")
    ap.add_argument("--retries", type=int, default=3, help="extra attempts per case after an API error")
    args = ap.parse_args()

    cases = load_cases()
    for c in cases:  # fail fast on a malformed label
        if c["expected"] is not None and not isinstance(c["expected"]["employees"], dict):
            ScheduleProblem(**c["expected"])
    runs = load_runs()
    RESULTS_DIR.mkdir(exist_ok=True)

    if not args.report_only:
        todo = [c for c in cases if not args.only or c["id"] in args.only]
        for i, case in enumerate(todo, 1):
            cached = runs.get(case["id"])
            if cached and cached["outcome"] != "api_error" and cached["model"] == args.model and not args.fresh:
                continue
            for attempt in range(args.retries + 1):
                rec = run_case(case, args.model, args.skip_baseline)
                if rec["outcome"] != "api_error" or attempt == args.retries:
                    break
                wait = 30 * (attempt + 1)
                print(f"    {case['id']}: API error, retrying in {wait} s ({rec['error'][:80]})", flush=True)
                time.sleep(wait)
            runs[case["id"]] = rec
            with RUNS_FILE.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(f"[{i}/{len(todo)}] {case['id']}: {rec['outcome']}"
                  + (f" exact={rec['score']['exact']}" if "score" in rec else "")
                  + (f" relax={len(rec['relaxations'])}" if "relaxations" in rec else "")
                  + (f" baseline_violations={len(rec['llm_only'].get('violations', []))}" if "llm_only" in rec else "")
                  + (f" ({rec.get('error', '')[:120]})" if rec["outcome"] != "ok" else ""), flush=True)
            time.sleep(args.pause)

    runs = {k: v for k, v in runs.items() if v["model"] == args.model}
    summary, md = build_report(cases, runs, args.model)
    write_results("llm_eval", {"meta": run_metadata(model=args.model), "summary": summary}, md)


if __name__ == "__main__":
    main()
