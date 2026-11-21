### Relaxation loop (tight suite)

192 over-constrained seeded instances (5-10 employees, 7/14 days, max 3-4 consecutive days, 15-30% unavailability). CP-SAT status before any relaxation: {'OPTIMAL': 90, 'INFEASIBLE': 102}. The 102 INFEASIBLE ones were sent through the agent (max 6 relaxations).

| Metric | Value |
|---|---|
| Recovered a schedule | 20/102 (19.6%) |
| Not recovered: stopped at the 6-relaxation cap | 82/102 (80.4%) |
| Not recovered: nothing left to relax, or timeout | 0/102 (0.0%) |
| Violations of the relaxed problem in recovered schedules | 0 |
| Mean relaxations per recovery | 3.65 (distribution {1: 6, 2: 1, 4: 4, 5: 5, 6: 4}) |
| Recoveries with at least one avoidable concession | 13/20 (65.0%) |
| Avoidable concessions / all concessions in recoveries | 33/73 (45.2%) |

Concession types used: {'consecutive_days': 39, 'morning_after_night': 13, 'unavailability': 21}. A concession is *avoidable* when undoing it alone still leaves a feasible problem, which proves the relaxation was not minimal.

| Unavailability rate | Max consecutive days | Infeasible instances | Recovered |
|---|---|---|---|
| 15% | 3 | 20 | 8/20 (40.0%) |
| 15% | 4 | 17 | 3/17 (17.6%) |
| 30% | 3 | 31 | 3/31 (9.7%) |
| 30% | 4 | 34 | 6/34 (17.6%) |