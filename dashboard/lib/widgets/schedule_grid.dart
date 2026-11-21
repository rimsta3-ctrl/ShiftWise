import 'package:material_ui/material_ui.dart';

import '../api/models.dart';
import '../theme.dart';

/// Employee x day grid. Cells are coloured by shift; unavailable days are marked, and an
/// unavailability dropped by the relaxation loop is outlined in red where it was overridden.
class ScheduleGrid extends StatelessWidget {
  const ScheduleGrid({super.key, required this.run});

  final RunResult run;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final p = run.problem;
    final assignments = run.result.assignments;
    final stillOff = p.unavailable.toSet();
    final ignored = run.originalProblem.unavailable.toSet().difference(stillOff);

    Widget header(String text, {String? sub}) => Padding(
          padding: const EdgeInsets.symmetric(vertical: 6),
          child: Column(
            children: [
              Text(text, style: theme.textTheme.labelMedium, textAlign: TextAlign.center),
              if (sub != null)
                Text(sub, style: theme.textTheme.labelSmall?.copyWith(color: scheme.onSurfaceVariant)),
            ],
          ),
        );

    Widget cell(String employee, int day) {
      final shift = assignments[employee]?[day];
      final key = Unavailability(employee, day);
      final unavailable = stillOff.contains(key);
      final overridden = ignored.contains(key);
      final color = shift == null ? null : shiftColor(context, shift, p.shifts);
      final tooltip = [
        '$employee · ${dayLabel(day, p.numDays)} (day $day)',
        shift ?? 'off',
        if (unavailable) 'unavailable (respected)',
        if (overridden) 'unavailability ignored by a relaxation',
      ].join('\n');
      return Tooltip(
        message: tooltip,
        child: Container(
          height: 32,
          margin: const EdgeInsets.all(2),
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: color ?? (unavailable ? scheme.surfaceContainerHighest : null),
            borderRadius: BorderRadius.circular(6),
            border: overridden
                ? Border.all(color: badColor(context), width: 2)
                : Border.all(color: scheme.outlineVariant.withValues(alpha: shift == null ? 1 : 0)),
          ),
          child: shift != null
              ? Text(shiftAbbrev(shift),
                  style: theme.textTheme.labelSmall?.copyWith(color: onColor(color!), fontWeight: FontWeight.w600))
              : unavailable
                  ? Icon(Icons.block, size: 14, color: scheme.onSurfaceVariant)
                  : Text('·', style: TextStyle(color: scheme.outline)),
        ),
      );
    }

    final table = Table(
      defaultVerticalAlignment: TableCellVerticalAlignment.middle,
      columnWidths: {
        0: const IntrinsicColumnWidth(),
        for (var d = 0; d < p.numDays; d++) d + 1: const FixedColumnWidth(54),
        p.numDays + 1: const FixedColumnWidth(52),
      },
      children: [
        TableRow(children: [
          header('Employee'),
          for (var d = 0; d < p.numDays; d++)
            header(dayLabel(d, p.numDays), sub: p.numDays > 7 ? dayNames[d % 7] : null),
          header('Shifts'),
        ]),
        for (final e in p.employees)
          TableRow(children: [
            Padding(
              padding: const EdgeInsets.only(right: 12),
              child: Text(e, style: theme.textTheme.bodyMedium, overflow: TextOverflow.ellipsis),
            ),
            for (var d = 0; d < p.numDays; d++) cell(e, d),
            Center(child: Text('${assignments[e]?.length ?? 0}', style: theme.textTheme.labelLarge)),
          ]),
      ],
    );

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SingleChildScrollView(scrollDirection: Axis.horizontal, child: table),
        const SizedBox(height: 12),
        Wrap(
          spacing: 14,
          runSpacing: 6,
          children: [
            for (final s in p.shifts) _Legend(color: shiftColor(context, s, p.shifts), label: s),
            _Legend(icon: Icons.block, label: 'unavailable'),
            if (ignored.isNotEmpty) _Legend(outline: badColor(context), label: 'unavailability ignored'),
          ],
        ),
      ],
    );
  }
}

class _Legend extends StatelessWidget {
  const _Legend({required this.label, this.color, this.icon, this.outline});

  final String label;
  final Color? color;
  final IconData? icon;
  final Color? outline;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 16,
          height: 16,
          decoration: BoxDecoration(
            color: color ?? scheme.surfaceContainerHighest,
            borderRadius: BorderRadius.circular(4),
            border: outline != null ? Border.all(color: outline!, width: 2) : null,
          ),
          child: icon != null ? Icon(icon, size: 12, color: scheme.onSurfaceVariant) : null,
        ),
        const SizedBox(width: 6),
        Text(label, style: Theme.of(context).textTheme.bodySmall),
      ],
    );
  }
}

/// Shifts per employee, stacked by shift type: what the fairness objective balances.
class LoadChart extends StatelessWidget {
  const LoadChart({super.key, required this.run});

  final RunResult run;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final p = run.problem;
    final loads = {
      for (final e in p.employees)
        e: {for (final s in p.shifts) s: (run.result.assignments[e]?.values.where((x) => x == s).length ?? 0)},
    };
    final totals = {for (final e in p.employees) e: loads[e]!.values.fold(0, (a, b) => a + b)};
    final maxTotal = totals.values.fold(0, (a, b) => a > b ? a : b);
    final minTotal = totals.values.fold(maxTotal, (a, b) => a < b ? a : b);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        for (final e in p.employees)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 3),
            child: Row(
              children: [
                SizedBox(width: 96, child: Text(e, overflow: TextOverflow.ellipsis, style: theme.textTheme.bodySmall)),
                Expanded(
                  child: LayoutBuilder(
                    builder: (context, constraints) {
                      final width = maxTotal == 0 ? 0.0 : constraints.maxWidth * totals[e]! / maxTotal;
                      return Align(
                        alignment: Alignment.centerLeft,
                        child: SizedBox(
                          width: width,
                          height: 18,
                          child: ClipRRect(
                            borderRadius: BorderRadius.circular(4),
                            child: Row(
                              children: [
                                for (final s in p.shifts)
                                  if (loads[e]![s]! > 0)
                                    Expanded(
                                      flex: loads[e]![s]!,
                                      child: Tooltip(
                                        message: '$e: ${loads[e]![s]} × $s',
                                        child: Container(color: shiftColor(context, s, p.shifts)),
                                      ),
                                    ),
                              ],
                            ),
                          ),
                        ),
                      );
                    },
                  ),
                ),
                SizedBox(
                  width: 32,
                  child: Text('${totals[e]}', textAlign: TextAlign.right, style: theme.textTheme.labelLarge),
                ),
              ],
            ),
          ),
        const SizedBox(height: 8),
        Text(
          'Most loaded $maxTotal, least loaded $minTotal → gap ${maxTotal - minTotal} '
          '(CP-SAT minimizes this gap; exact staffing means no shift is added just to even it out).',
          style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.onSurfaceVariant),
        ),
      ],
    );
  }
}

/// Staff assigned per (shift, day) against the requirement.
class CoverageTable extends StatelessWidget {
  const CoverageTable({super.key, required this.run});

  final RunResult run;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final p = run.problem;
    int staffed(int day, String shift) =>
        run.result.assignments.values.where((days) => days[day] == shift).length;
    final allExact = [
      for (var d = 0; d < p.numDays; d++)
        for (final s in p.shifts) staffed(d, s) == p.minStaffPerShift,
    ].every((ok) => ok);

    final table = Table(
      defaultVerticalAlignment: TableCellVerticalAlignment.middle,
      columnWidths: {
        0: const IntrinsicColumnWidth(),
        for (var d = 0; d < p.numDays; d++) d + 1: const FixedColumnWidth(44),
      },
      children: [
        TableRow(children: [
          const SizedBox.shrink(),
          for (var d = 0; d < p.numDays; d++)
            Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: Text(dayLabel(d, p.numDays), textAlign: TextAlign.center, style: theme.textTheme.labelSmall),
            ),
        ]),
        for (final s in p.shifts)
          TableRow(children: [
            Padding(
              padding: const EdgeInsets.only(right: 10),
              child: Row(mainAxisSize: MainAxisSize.min, children: [
                Container(width: 10, height: 10, color: shiftColor(context, s, p.shifts)),
                const SizedBox(width: 6),
                Text(s, style: theme.textTheme.bodySmall),
              ]),
            ),
            for (var d = 0; d < p.numDays; d++)
              Builder(builder: (context) {
                final n = staffed(d, s);
                final color = n == p.minStaffPerShift
                    ? goodColor(context)
                    : n < p.minStaffPerShift
                        ? badColor(context)
                        : warnColor(context);
                return Container(
                  margin: const EdgeInsets.all(2),
                  height: 26,
                  alignment: Alignment.center,
                  decoration: BoxDecoration(
                    color: color.withValues(alpha: 0.12),
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text('$n', style: theme.textTheme.labelMedium?.copyWith(color: color)),
                );
              }),
          ]),
      ],
    );

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SingleChildScrollView(scrollDirection: Axis.horizontal, child: table),
        const SizedBox(height: 8),
        Row(
          children: [
            Icon(allExact ? Icons.check_circle : Icons.warning_amber,
                size: 16, color: allExact ? goodColor(context) : warnColor(context)),
            const SizedBox(width: 6),
            Expanded(
              child: Text(
                allExact
                    ? 'Every shift has exactly ${p.minStaffPerShift} person(s), as required.'
                    : 'Some shifts differ from the requirement of ${p.minStaffPerShift}.',
                style: theme.textTheme.bodySmall,
              ),
            ),
          ],
        ),
      ],
    );
  }
}

/// Constraint values as extracted vs after the relaxations, changed rows highlighted.
class ConstraintDiff extends StatelessWidget {
  const ConstraintDiff({super.key, required this.original, required this.current});

  final ScheduleProblem? original;
  final ScheduleProblem? current;

  static String _unav(ScheduleProblem p) {
    if (p.unavailable.isEmpty) return 'none';
    final byEmployee = <String, List<int>>{};
    for (final u in p.unavailable) {
      byEmployee.putIfAbsent(u.employee, () => []).add(u.day);
    }
    return byEmployee.entries
        .map((e) => '${e.key}: ${e.value.map((d) => dayLabel(d, p.numDays)).join(', ')}')
        .join('; ');
  }

  static List<(String, String Function(ScheduleProblem))> get _rows => [
        ('Employees', (p) => '${p.employees.length}: ${p.employees.join(', ')}'),
        ('Days', (p) => '${p.numDays}'),
        ('Shifts', (p) => p.shifts.join(', ')),
        ('Staff per shift', (p) => '${p.minStaffPerShift}'),
        ('Max consecutive days', (p) => '${p.maxConsecutiveDays}'),
        ('No morning after night', (p) => p.noMorningAfterNight ? 'yes' : 'no'),
        ('Unavailability', _unav),
      ];

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    if (original == null || current == null) {
      return Text('The extracted problem will appear here.',
          style: theme.textTheme.bodyMedium?.copyWith(color: scheme.onSurfaceVariant));
    }
    TableRow row(String label, String a, String b, {bool header = false}) {
      final changed = !header && a != b;
      final style = header ? theme.textTheme.labelMedium : theme.textTheme.bodySmall;
      Widget c(String text, {bool strong = false}) => Padding(
            padding: const EdgeInsets.symmetric(vertical: 6, horizontal: 8),
            child: Text(text, style: strong ? style?.copyWith(fontWeight: FontWeight.w700) : style),
          );
      return TableRow(
        decoration: BoxDecoration(color: changed ? scheme.tertiaryContainer.withValues(alpha: 0.6) : null),
        children: [c(label), c(a), c(b, strong: changed)],
      );
    }

    return Table(
      columnWidths: const {0: IntrinsicColumnWidth(), 1: FlexColumnWidth(), 2: FlexColumnWidth()},
      border: TableBorder(horizontalInside: BorderSide(color: scheme.outlineVariant)),
      children: [
        row('Constraint', 'As extracted', 'Used for the schedule', header: true),
        for (final (label, value) in _rows) row(label, value(original!), value(current!)),
      ],
    );
  }
}
