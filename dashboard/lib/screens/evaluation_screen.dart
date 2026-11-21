import 'package:material_ui/material_ui.dart';

import '../api/client.dart';
import '../theme.dart';
import '../widgets/common.dart';

typedef Json = Map<String, dynamic>;

num _n(Object? v) => (v as num?) ?? 0;

double? _median(List<num> values) {
  if (values.isEmpty) return null;
  final s = [...values]..sort();
  final mid = s.length ~/ 2;
  return s.length.isOdd ? s[mid].toDouble() : (s[mid - 1] + s[mid]) / 2;
}

double? _mean(Iterable<num> values) {
  final list = values.toList();
  return list.isEmpty ? null : list.fold<num>(0, (a, b) => a + b) / list.length;
}

String _f(num? v, [int digits = 2]) => v == null ? 'n/a' : v.toStringAsFixed(digits);

/// Measured results produced by evaluation/*.py, served by GET /evaluation.
class EvaluationScreen extends StatefulWidget {
  const EvaluationScreen({super.key, required this.api});

  final ApiClient api;

  @override
  State<EvaluationScreen> createState() => _EvaluationScreenState();
}

class _EvaluationScreenState extends State<EvaluationScreen> {
  late Future<Json> _future = widget.api.evaluation();

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<Json>(
      future: _future,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snapshot.hasError) {
          return Center(
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              Text('Could not load /evaluation: ${snapshot.error}'),
              const SizedBox(height: 8),
              FilledButton(
                onPressed: () => setState(() => _future = widget.api.evaluation()),
                child: const Text('Retry'),
              ),
            ]),
          );
        }
        final data = snapshot.data!;
        return SingleChildScrollView(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(children: [
                Expanded(
                  child: Text(
                    'Every number below is read from evaluation/results/*.json, written by the benchmark scripts. '
                    'Nothing is computed from estimates.',
                    style: Theme.of(context).textTheme.bodyMedium,
                  ),
                ),
                IconButton(
                  tooltip: 'Reload',
                  onPressed: () => setState(() => _future = widget.api.evaluation()),
                  icon: const Icon(Icons.refresh),
                ),
              ]),
              const SizedBox(height: 16),
              _SolverSection(data: data['solver_benchmark'] as Json?),
              const SizedBox(height: 16),
              _RelaxationSection(data: data['relaxation_benchmark'] as Json?),
              const SizedBox(height: 16),
              _LlmSection(data: data['llm_eval'] as Json?, cases: (data['llm_cases'] as List?)?.cast<Json>() ?? []),
            ],
          ),
        );
      },
    );
  }
}

String _metaLine(Json meta) =>
    'measured ${meta['date_utc']} UTC · ${meta['cpu']} · ${meta['cpu_count']} threads · '
    'OR-Tools ${(meta['packages'] as Json?)?['ortools']}';

class _Missing extends StatelessWidget {
  const _Missing(this.title, this.command);

  final String title;
  final String command;

  @override
  Widget build(BuildContext context) => SectionCard(
        title: title,
        icon: Icons.hourglass_empty,
        child: Text('No results on disk yet. Run: $command'),
      );
}

/// A compact table built from rows of strings.
class _SimpleTable extends StatelessWidget {
  const _SimpleTable({required this.header, required this.rows});

  final List<String> header;
  final List<List<String>> rows;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    Widget cell(String t, {bool head = false}) => Padding(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
          child: Text(t, style: head ? theme.textTheme.labelMedium : theme.textTheme.bodySmall),
        );
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Table(
        defaultColumnWidth: const IntrinsicColumnWidth(),
        border: TableBorder(horizontalInside: BorderSide(color: theme.colorScheme.outlineVariant)),
        children: [
          TableRow(children: [for (final h in header) cell(h, head: true)]),
          for (final r in rows) TableRow(children: [for (final v in r) cell(v)]),
        ],
      ),
    );
  }
}

class _Bars extends StatelessWidget {
  const _Bars({required this.values, required this.unit});

  final Map<String, double> values;
  final String unit;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final max = values.values.fold<double>(0, (a, b) => a > b ? a : b);
    return Column(children: [
      for (final e in values.entries)
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 3),
          child: Row(children: [
            SizedBox(width: 110, child: Text(e.key, style: theme.textTheme.bodySmall)),
            Expanded(
              child: LayoutBuilder(
                builder: (context, c) => Align(
                  alignment: Alignment.centerLeft,
                  child: Container(
                    width: max == 0 ? 0 : c.maxWidth * e.value / max,
                    height: 16,
                    decoration: BoxDecoration(
                      color: theme.colorScheme.primary.withValues(alpha: 0.75),
                      borderRadius: BorderRadius.circular(4),
                    ),
                  ),
                ),
              ),
            ),
            SizedBox(
              width: 72,
              child: Text('${e.value.toStringAsFixed(3)} $unit', textAlign: TextAlign.right, style: theme.textTheme.bodySmall),
            ),
          ]),
        ),
    ]);
  }
}

class _SolverSection extends StatelessWidget {
  const _SolverSection({required this.data});

  final Json? data;

  @override
  Widget build(BuildContext context) {
    if (data == null) return const _Missing('Solver benchmark', 'python -m evaluation.bench_solver');
    final s = data!['summary'] as Json;
    final rows = (data!['rows'] as List).cast<Json>();
    final statuses = (s['cpsat_status_counts'] as Json?) ?? {};
    final solvedStatuses = {'OPTIMAL', 'FEASIBLE'};

    final bandRows = <List<String>>[];
    for (final band in ['light', 'medium', 'heavy']) {
      final g = rows.where((r) => r['band'] == band).toList();
      if (g.isEmpty) continue;
      final solved = g.where((r) => solvedStatuses.contains(r['cpsat_status'])).toList();
      final both = solved.where((r) => r['greedy_valid'] == true).toList();
      bandRows.add([
        band,
        '${g.length}',
        '${g.where((r) => r['cpsat_status'] == 'INFEASIBLE').length}',
        pctText(solved.length, solved.length),
        pctText(both.length, solved.length),
        '${_f(_mean(both.map((r) => _n(r['cpsat_gap']))))} / ${_f(_mean(both.map((r) => _n(r['greedy_gap']))))}',
        '${_f(_median(g.map((r) => _n(r['cpsat_time_s'])).toList()), 3)} s',
      ]);
    }
    final sizes = rows.map((r) => _n(r['n']).toInt()).toSet().toList()..sort();
    final timeBySize = {
      for (final n in sizes)
        '$n employees': _median(rows.where((r) => _n(r['n']) == n).map((r) => _n(r['cpsat_time_s'])).toList())!,
    };

    return SectionCard(
      title: 'Solver benchmark: CP-SAT vs greedy',
      subtitle: '${s['instances']} seeded instances · ${_metaLine(data!['meta'] as Json)}',
      icon: Icons.memory,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          KpiWrap(children: [
            KpiTile(
              label: 'Violations (independent check)',
              value: '${s['cpsat_total_violations']}',
              caption: 'in ${s['cpsat_schedules_returned']} CP-SAT schedules',
              color: _n(s['cpsat_total_violations']) == 0 ? goodColor(context) : badColor(context),
              icon: Icons.shield_outlined,
            ),
            KpiTile(
              label: 'Unrequested shifts',
              value: '${s['cpsat_total_extra_shifts']}',
              caption: 'exact coverage',
              icon: Icons.event_busy,
            ),
            KpiTile(
              label: 'Fairness proven optimal',
              value: '${s['cpsat_proven_optimal']}/${s['instances']}',
              caption: '${statuses['INFEASIBLE'] ?? 0} proven infeasible',
              icon: Icons.balance,
            ),
            KpiTile(
              label: 'Solve time median / p95',
              value: '${_f(_n(s['cpsat_time_median_s']), 3)} / ${_f(_n(s['cpsat_time_p95_s']), 3)} s',
              caption: 'max ${_f(_n(s['cpsat_time_max_s']), 3)} s',
              icon: Icons.timer_outlined,
            ),
            KpiTile(
              label: 'Greedy valid',
              value: pctText(_n(s['greedy_valid_on_solvable']), _n(s['cpsat_schedules_returned'])),
              caption: 'on instances CP-SAT solved',
              icon: Icons.auto_fix_normal,
            ),
            KpiTile(
              label: 'Greedy reaches optimal gap',
              value: pctText(_n(s['greedy_reaches_optimal_gap']), _n(s['greedy_compared_to_proven_optimum'])),
              caption: 'worst excess ${s['greedy_max_excess_gap']} shifts',
              icon: Icons.compare_arrows,
            ),
          ]),
          const SizedBox(height: 16),
          TwoColumns(
            left: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('By load band (share of the team needed every day)', style: Theme.of(context).textTheme.labelLarge),
              const SizedBox(height: 6),
              _SimpleTable(
                header: const ['Band', 'Instances', 'Infeasible', 'CP-SAT valid', 'Greedy valid', 'Gap CP-SAT / greedy*', 'Median time'],
                rows: bandRows,
              ),
              const SizedBox(height: 4),
              Text('* mean gap on instances where both produced a valid schedule',
                  style: Theme.of(context).textTheme.bodySmall),
            ]),
            right: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('Median CP-SAT time by team size', style: Theme.of(context).textTheme.labelLarge),
              const SizedBox(height: 6),
              _Bars(values: timeBySize, unit: 's'),
            ]),
          ),
        ],
      ),
    );
  }
}

class _RelaxationSection extends StatelessWidget {
  const _RelaxationSection({required this.data});

  final Json? data;

  @override
  Widget build(BuildContext context) {
    if (data == null) return const _Missing('Relaxation stress test', 'python -m evaluation.bench_solver --suite tight');
    final s = data!['summary'] as Json;
    final rows = (data!['rows'] as List).cast<Json>().where((r) => r['initial_status'] == 'INFEASIBLE').toList();
    final kinds = (s['concession_kinds_used'] as Json?) ?? {};

    final rates = rows.map((r) => _n(r['p_unavailable'])).toSet().toList()..sort();
    final ks = rows.map((r) => _n(r['max_consecutive'])).toSet().toList()..sort();
    final table = <List<String>>[
      for (final p in rates)
        for (final k in ks)
          () {
            final g = rows.where((r) => _n(r['p_unavailable']) == p && _n(r['max_consecutive']) == k).toList();
            return ['${(p * 100).round()}%', '$k', '${g.length}', pctText(g.where((r) => r['recovered'] == true).length, g.length)];
          }(),
    ];

    return SectionCard(
      title: 'Relaxation loop: stress test',
      subtitle: '${s['infeasible']} instances proven INFEASIBLE before relaxation · ${_metaLine(data!['meta'] as Json)}',
      icon: Icons.tune,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          KpiWrap(children: [
            KpiTile(
              label: 'Schedule recovered',
              value: pctText(_n(s['recovered']), _n(s['infeasible'])),
              icon: Icons.healing,
            ),
            KpiTile(
              label: 'Stopped at the cap',
              value: pctText(_n(s['not_recovered_hit_cap']), _n(s['infeasible'])),
              caption: 'max relaxations reached',
              color: warnColor(context),
              icon: Icons.block,
            ),
            KpiTile(
              label: 'Avoidable concessions',
              value: pctText(_n(s['avoidable_concessions_total']), _n(s['concessions_total'])),
              caption: 'undoing it alone stays feasible',
              color: warnColor(context),
              icon: Icons.undo,
            ),
            KpiTile(
              label: 'Violations after relaxing',
              value: '${s['final_violations_total']}',
              caption: 'vs the relaxed problem',
              color: _n(s['final_violations_total']) == 0 ? goodColor(context) : badColor(context),
              icon: Icons.shield_outlined,
            ),
            KpiTile(
              label: 'Mean relaxations',
              value: _f(s['relaxations_mean'] as num?),
              caption: 'per recovery',
              icon: Icons.repeat,
            ),
          ]),
          const SizedBox(height: 12),
          Wrap(spacing: 6, runSpacing: 6, children: [
            for (final e in kinds.entries) Chip(label: Text('${e.key}: ${e.value}')),
          ]),
          const SizedBox(height: 12),
          Text('Recovery rate by unavailability rate and max consecutive days',
              style: Theme.of(context).textTheme.labelLarge),
          const SizedBox(height: 6),
          _SimpleTable(header: const ['Unavailability', 'Max in a row', 'Infeasible', 'Recovered'], rows: table),
          const SizedBox(height: 8),
          Text(
            'The policy follows a fixed order and drops unavailabilities in list order, without knowing which '
            'constraint causes the conflict. That is why it is a heuristic and not a minimal relaxation.',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
      ),
    );
  }
}

class _LlmSection extends StatelessWidget {
  const _LlmSection({required this.data, required this.cases});

  final Json? data;
  final List<Json> cases;

  @override
  Widget build(BuildContext context) {
    if (data == null) return const _Missing('LLM evaluation', 'python -m evaluation.eval_llm');
    final theme = Theme.of(context);
    final s = data!['summary'] as Json;
    final apiErrors = (s['cases_api_error'] as List?) ?? [];
    final invented = ((s['invented_constraint_cases'] as Json?) ?? {}).length;

    Widget outcomeChip(String outcome) => StatusChip(
          outcome,
          color: switch (outcome) {
            'ok' => goodColor(context),
            'rejected' => theme.colorScheme.secondary,
            'api_error' => warnColor(context),
            _ => theme.colorScheme.outline,
          },
        );

    return SectionCard(
      title: 'LLM evaluation (${s['model']})',
      subtitle: '${s['cases_completed']}/${s['cases_total']} labelled requests completed · '
          'measured ${(data!['meta'] as Json)['date_utc']} UTC',
      icon: Icons.translate,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (apiErrors.isNotEmpty)
            Container(
              margin: const EdgeInsets.only(bottom: 12),
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: warnColor(context).withValues(alpha: 0.12),
                borderRadius: BorderRadius.circular(10),
              ),
              child: Text(
                'Partial run: ${apiErrors.length} request(s) hit LLM API errors (provider overload) and are not '
                'counted. Rerun "python -m evaluation.eval_llm" to complete them. The categories are not equally '
                'represented until then.',
                style: theme.textTheme.bodySmall,
              ),
            ),
          KpiWrap(children: [
            KpiTile(
              label: 'Extraction exact match',
              value: pctText(_n(s['extraction_exact']), _n(s['extraction_scored'])),
              caption: 'all 7 fields vs gold label',
              icon: Icons.fact_check_outlined,
            ),
            KpiTile(
              label: 'Valid on first attempt',
              value: pctText(_n(s['extraction_first_try']), _n(s['extraction_plannable'])),
              icon: Icons.looks_one_outlined,
            ),
            KpiTile(
              label: 'Invented constraints',
              value: pctText(invented, _n(s['extraction_scored'])),
              caption: 'requests affected',
              icon: Icons.psychology_alt_outlined,
            ),
            KpiTile(
              label: 'LLM-only schedules valid',
              value: pctText(_n(s['baseline_valid']), _n(s['baseline_attempted'])),
              caption: 'same model writes the schedule',
              color: warnColor(context),
              icon: Icons.smart_toy_outlined,
            ),
            KpiTile(
              label: 'ShiftWise schedules valid',
              value: pctText(_n(s['unrelaxed_clean_vs_gold']), _n(s['unrelaxed_checked_vs_gold'])),
              caption: 'checked against the gold problem',
              color: goodColor(context),
              icon: Icons.verified_outlined,
            ),
            KpiTile(
              label: 'Pipeline latency',
              value: '${_f(s['pipeline_time_median_s'] as num?, 1)} s',
              caption: 'median, p95 ${_f(s['pipeline_time_p95_s'] as num?, 1)} s',
              icon: Icons.timer_outlined,
            ),
          ]),
          const SizedBox(height: 16),
          Text('Per request', style: theme.textTheme.labelLarge),
          const SizedBox(height: 6),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: DataTable(
              headingRowHeight: 36,
              dataRowMinHeight: 32,
              dataRowMaxHeight: 48,
              columns: const [
                DataColumn(label: Text('Id')),
                DataColumn(label: Text('Category')),
                DataColumn(label: Text('Outcome')),
                DataColumn(label: Text('Exact')),
                DataColumn(label: Text('Relaxations'), numeric: true),
                DataColumn(label: Text('LLM-only violations'), numeric: true),
                DataColumn(label: Text('Time (s)'), numeric: true),
                DataColumn(label: Text('Request')),
              ],
              rows: [
                for (final c in cases)
                  DataRow(cells: [
                    DataCell(Text('${c['id']}')),
                    DataCell(Text('${c['category']}')),
                    DataCell(outcomeChip('${c['outcome']}')),
                    DataCell(c['exact'] == null
                        ? const Text('—')
                        : Icon(c['exact'] == true ? Icons.check : Icons.close,
                            size: 18, color: c['exact'] == true ? goodColor(context) : badColor(context))),
                    DataCell(Text(c['relaxations'] == null ? '—' : '${c['relaxations']}')),
                    DataCell(Text(c['baseline_violations'] == null ? '—' : '${c['baseline_violations']}')),
                    DataCell(Text(c['total_time_s'] == null ? '—' : _f(c['total_time_s'] as num, 1))),
                    DataCell(SizedBox(
                      width: 420,
                      child: Tooltip(
                        message: '${c['request']}',
                        child: Text('${c['request']}', overflow: TextOverflow.ellipsis),
                      ),
                    )),
                  ]),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
