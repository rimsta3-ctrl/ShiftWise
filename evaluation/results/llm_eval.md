### LLM evaluation (gemini-3.5-flash-lite)

43 hand-labelled requests (6 in French), 17 completed; not completed because of API errors: shifts-02, shifts-03, shifts-04, flags-01, flags-02, flags-03, distractor-01, distractor-02, distractor-03, distractor-04, distractor-05, distractor-06, fr-01, fr-02, fr-03, fr-04, fr-05, fr-06, infeasible-01, infeasible-02, infeasible-03, infeasible-04, infeasible-05, reject-01, reject-02, reject-03. One run per request, so no variance estimate (temperature 0 is requested, but some Gemini models use fixed sampling and ignore it).

**Extraction (text -> ScheduleProblem)**

| Metric | Value |
|---|---|
| Valid ScheduleProblem within 3 attempts | 17/17 (100.0%) |
| Valid on the first attempt | 17/17 (100.0%) |
| Requests rescued by the validation-feedback retry | 0 |
| Exact match with the gold label (all 7 fields) | 17/17 (100.0%) |
| Requests with an invented constraint | 0/17 (0.0%) |
| Unplannable requests correctly rejected | 0/0 |

| Field | Accuracy |
|---|---|
| employees | 17/17 (100.0%) |
| num_days | 17/17 (100.0%) |
| shifts | 17/17 (100.0%) |
| min_staff_per_shift | 17/17 (100.0%) |
| max_consecutive_days | 17/17 (100.0%) |
| unavailable | 17/17 (100.0%) |
| no_morning_after_night | 17/17 (100.0%) |

| Category | Exact match |
|---|---|
| basic | 6/6 (100.0%) |
| headcount | 4/4 (100.0%) |
| day_expressions | 6/6 (100.0%) |
| shifts_horizon | 1/1 (100.0%) |
| flags | 0/0 |
| out_of_scope | 0/0 |
| french | 0/0 |
| infeasible | 0/0 |

**End to end (LangGraph agent)**

| Metric | Value |
|---|---|
| Schedules returned | 17/17 (100.0%) of valid extractions |
| Violations of the extracted problem (independent checker) | 0 |
| Schedules without relaxation that also satisfy the gold problem (user intent) | 17/17 (100.0%) |
| Requests that triggered relaxation | 0 |
| ... whose explanation mentions every concession (keyword check) | 0/0 |
| Explanations that fell back to the template | 0/17 (0.0%) |
| Pipeline latency, median / p95 | 17.9 s / 38.7 s |

**LLM-only baseline (the same model writes the schedule itself)**

| Metric | LLM only | ShiftWise |
|---|---|---|
| Feasible requests: schedule satisfies every hard constraint of the gold problem | 11/16 (68.8%) | 17/17 (100.0%) |
| Infeasible requests: schedule returned that silently breaks constraints | 0/0 | 0/0 |

LLM-only violation types (requests affected): {'double_booking': 2, 'consecutive_days': 1, 'morning_after_night': 1, 'unavailability': 3, 'malformed': 1}; no usable output on 0 request(s).