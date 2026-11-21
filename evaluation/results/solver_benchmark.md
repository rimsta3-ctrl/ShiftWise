### Solver benchmark (standard suite)

216 seeded random instances: 8-50 employees, 7/14/28 days, 3 shifts, 1-12 staff per shift, 10% random unavailability, max 5 consecutive days, no morning after night. CP-SAT time limit 10 s, 8 workers. Load = share of the team needed every day.

- CP-SAT returned a schedule on 206/216 (95.4%) instances; statuses {'OPTIMAL': 206, 'INFEASIBLE': 10} (INFEASIBLE = proven impossible).
- Independent checker: **0 constraint violations** and 0 unrequested shifts in CP-SAT schedules.
- Fairness optimality proven on 206/216 (95.4%); gap <= 1 shift on 198/206 (96.1%) of CP-SAT schedules.
- Greedy baseline produced a valid schedule on 204/206 (99.0%) of the instances CP-SAT solved (4 under-staffed slots in total). On the 204 instances both solved, mean fairness gap: CP-SAT 0.95 vs greedy 1.28 shifts; greedy matched the proven-optimal gap on 152/204 (74.5%) (worst excess: 3 shifts). Greedy cannot prove a request impossible; CP-SAT's INFEASIBLE proofs are what trigger the relaxation loop.
- CP-SAT wall time: median 0.535 s, p95 2.186 s, max 2.930 s.

| Load band | Instances | Proven infeasible | CP-SAT valid | Greedy valid | Mean gap CP-SAT / greedy* | Median / p95 time (s) |
|---|---|---|---|---|---|---|
| light (<= 40%) | 117 | 0 | 117/117 (100.0%) | 117/117 (100.0%) | 0.97 / 1.09 | 0.561 / 2.327 |
| medium (<= 60%) | 54 | 0 | 54/54 (100.0%) | 54/54 (100.0%) | 0.80 / 1.20 | 0.520 / 1.701 |
| heavy (<= 75%) | 45 | 10 | 35/35 (100.0%) | 33/35 (94.3%) | 1.09 / 2.09 | 0.430 / 2.074 |

\* on instances where both produced a valid schedule. "Valid" columns are over the instances CP-SAT solved (proven-infeasible ones excluded).

| Employees | Instances | Median time (s) | p95 time (s) | Max time (s) |
|---|---|---|---|---|
| 8 | 18 | 0.213 | 0.885 | 0.885 |
| 12 | 27 | 0.346 | 1.019 | 1.856 |
| 20 | 45 | 0.509 | 2.186 | 2.805 |
| 30 | 54 | 0.776 | 2.660 | 2.930 |
| 50 | 72 | 0.622 | 1.833 | 2.769 |