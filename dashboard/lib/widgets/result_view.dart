import 'package:material_ui/material_ui.dart';

import '../api/models.dart';
import '../state/run_controller.dart';
import '../theme.dart';
import 'common.dart';
import 'schedule_grid.dart';

/// Everything shown once (or while) a run produces a result.
class ResultView extends StatelessWidget {
  const ResultView({super.key, required this.controller});

  final RunController controller;

  @override
  Widget build(BuildContext context) {
    final c = controller;
    final run = c.result;
    final children = <Widget>[];

    if (c.error != null) children.add(_ErrorCard(controller: c));
    if (run == null) {
      if (!c.hasRun) children.add(const _EmptyState());
      return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: _spaced(children));
    }

    children.add(_Kpis(run: run));
    if (run.result.hasSchedule) {
      children.add(SectionCard(
        title: 'Schedule',
        subtitle: 'Hover a cell for details. Shift counts per employee in the last column.',
        icon: Icons.calendar_view_week,
        child: ScheduleGrid(run: run),
      ));
      children.add(TwoColumns(
        left: SectionCard(
          title: 'Load per employee',
          subtitle: 'Fairness objective: minimize most loaded − least loaded',
          icon: Icons.bar_chart,
          child: LoadChart(run: run),
        ),
        right: SectionCard(
          title: 'Coverage per shift and day',
          subtitle: 'Assigned staff vs requirement',
          icon: Icons.grid_on,
          child: CoverageTable(run: run),
        ),
      ));
    }
    children.add(TwoColumns(
      left: _ExplanationCard(run: run),
      right: _VerificationCard(run: run),
    ));
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: _spaced(children));
  }

  static List<Widget> _spaced(List<Widget> items) => [
        for (var i = 0; i < items.length; i++) ...[if (i > 0) const SizedBox(height: 16), items[i]],
      ];
}

class _EmptyState extends StatelessWidget {
  const _EmptyState();

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return SectionCard(
      title: 'Results',
      icon: Icons.insights,
      child: Text(
        'Pick an example and press "Run the agent". You will see each node of the graph start and finish, '
        'every routing decision with its reason, each relaxation, the final schedule and the independent check.',
        style: theme.textTheme.bodyMedium?.copyWith(color: theme.colorScheme.onSurfaceVariant),
      ),
    );
  }
}

class _ErrorCard extends StatelessWidget {
  const _ErrorCard({required this.controller});

  final RunController controller;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final status = controller.errorStatus;
    final hint = switch (status) {
      503 => 'The LLM provider is unavailable or overloaded. Structured mode needs no LLM.',
      422 => 'The request could not be turned into a valid problem (or the input failed validation).',
      null => 'Is the API running? Start it with: uvicorn api:app --reload',
      _ => null,
    };
    return Card(
      color: theme.colorScheme.errorContainer,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(Icons.error_outline, color: theme.colorScheme.onErrorContainer),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(status == null ? 'Run failed' : 'Run failed (HTTP $status)',
                      style: theme.textTheme.titleSmall?.copyWith(color: theme.colorScheme.onErrorContainer)),
                  const SizedBox(height: 4),
                  SelectableText(controller.error ?? '',
                      style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.onErrorContainer)),
                  if (hint != null) ...[
                    const SizedBox(height: 6),
                    Text(hint, style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.onErrorContainer)),
                  ],
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _Kpis extends StatelessWidget {
  const _Kpis({required this.run});

  final RunResult run;

  @override
  Widget build(BuildContext context) {
    final r = run.result;
    final violations = run.violations.length;
    return SectionCard(
      title: 'Outcome',
      icon: Icons.speed,
      child: KpiWrap(children: [
        KpiTile(label: 'Solver status', value: r.status, color: statusColor(context, r.status), icon: Icons.memory),
        KpiTile(
          label: 'Fairness gap',
          value: r.shiftGap == null ? '—' : '${r.shiftGap} shift${r.shiftGap == 1 ? '' : 's'}',
          caption: 'most − least loaded',
          icon: Icons.balance,
        ),
        KpiTile(
          label: 'Shifts assigned',
          value: r.hasSchedule ? '${r.assignedShifts} / ${run.requiredShifts}' : '—',
          caption: 'assigned / required',
          icon: Icons.event_available,
        ),
        KpiTile(
          label: 'Relaxations',
          value: '${run.relaxations.length}',
          caption: run.relaxations.isEmpty ? 'request kept as stated' : 'concessions, listed below',
          color: run.relaxations.isEmpty ? null : warnColor(context),
          icon: Icons.tune,
        ),
        KpiTile(
          label: 'Independent check',
          value: run.verified ? '$violations violation${violations == 1 ? '' : 's'}' : 'no schedule',
          caption: 'validator.py, not the solver',
          color: run.verified ? (violations == 0 ? goodColor(context) : badColor(context)) : null,
          icon: Icons.shield_outlined,
        ),
        KpiTile(
          label: 'Total time',
          value: formatMs(run.totalMs),
          caption: 'last solve ${r.solveTimeS.toStringAsFixed(3)} s',
          icon: Icons.timer_outlined,
        ),
      ]),
    );
  }
}

class _ExplanationCard extends StatelessWidget {
  const _ExplanationCard({required this.run});

  final RunResult run;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return SectionCard(
      title: 'Explanation',
      subtitle: run.explanationSource == 'llm'
          ? 'Written by the LLM from the solver facts only'
          : 'Deterministic template (no LLM call, or the LLM call failed)',
      icon: Icons.chat_bubble_outline,
      trailing: StatusChip(run.explanationSource == 'llm' ? 'LLM' : 'template', color: theme.colorScheme.secondary),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SelectableText(run.explanation, style: theme.textTheme.bodyMedium),
          if (run.relaxations.isNotEmpty) ...[
            const SizedBox(height: 12),
            Text('Concessions made by the relaxation loop', style: theme.textTheme.labelLarge),
            const SizedBox(height: 4),
            for (final (i, note) in run.relaxations.indexed)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 2),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Icon(Icons.warning_amber, size: 16, color: warnColor(context)),
                    const SizedBox(width: 6),
                    Expanded(child: Text('${i + 1}. $note', style: theme.textTheme.bodySmall)),
                  ],
                ),
              ),
          ],
        ],
      ),
    );
  }
}

class _VerificationCard extends StatelessWidget {
  const _VerificationCard({required this.run});

  final RunResult run;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final ok = run.verified && run.violations.isEmpty;
    return SectionCard(
      title: 'Independent verification',
      subtitle: 'validator.py re-checks every hard constraint without using the CP-SAT model',
      icon: Icons.shield_outlined,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            Icon(ok ? Icons.verified : (run.verified ? Icons.gpp_bad : Icons.info_outline),
                color: ok ? goodColor(context) : (run.verified ? badColor(context) : theme.colorScheme.onSurfaceVariant)),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                !run.verified
                    ? 'No schedule was produced, so there is nothing to check.'
                    : ok
                        ? 'The schedule satisfies every hard constraint of the problem below.'
                        : '${run.violations.length} violation(s) found:',
                style: theme.textTheme.bodyMedium,
              ),
            ),
          ]),
          for (final v in run.violations.take(20))
            Padding(padding: const EdgeInsets.only(left: 32, top: 2), child: Text('• $v', style: theme.textTheme.bodySmall)),
          const SizedBox(height: 10),
          Text('Checked: one shift per person per day · at least the required staff per shift · unavailability · '
              'max ${run.problem.maxConsecutiveDays} consecutive days · '
              'rest rule ${run.problem.noMorningAfterNight ? 'on' : 'off'}.',
              style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.onSurfaceVariant)),
        ],
      ),
    );
  }
}
