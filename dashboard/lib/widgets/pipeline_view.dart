import 'dart:async';

import 'package:material_ui/material_ui.dart';

import '../state/run_controller.dart';
import '../theme.dart';
import 'common.dart';

class _NodeSpec {
  const _NodeSpec(this.id, this.title, this.subtitle, this.icon);

  final String id;
  final String title;
  final String subtitle;
  final IconData icon;
}

const _extract = _NodeSpec('extract', 'Extract', 'LLM → ScheduleProblem\nvalidated by Pydantic', Icons.translate);
const _solve = _NodeSpec('solve', 'Solve', 'OR-Tools CP-SAT\nexact coverage, min gap', Icons.memory);
const _relax = _NodeSpec('relax', 'Relax', 'loosen ONE constraint\nleast harmful first', Icons.tune);
const _explain = _NodeSpec('explain', 'Explain', 'LLM narration\ntemplate fallback', Icons.chat_bubble_outline);

/// The LangGraph agent drawn as it really is: extract → solve → explain, with the
/// conditional solve ⇄ relax loop underneath solve.
class PipelineView extends StatefulWidget {
  const PipelineView({super.key, required this.controller, this.maxRelaxations = 6});

  final RunController controller;
  final int maxRelaxations;

  @override
  State<PipelineView> createState() => _PipelineViewState();
}

class _PipelineViewState extends State<PipelineView> {
  Timer? _ticker;

  @override
  void initState() {
    super.initState();
    // Refresh the elapsed-time counter while a run is in progress
    _ticker = Timer.periodic(const Duration(milliseconds: 200), (_) {
      if (widget.controller.running && mounted) setState(() {});
    });
  }

  @override
  void dispose() {
    _ticker?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = widget.controller;
    final theme = Theme.of(context);
    final route = c.lastRoute;
    final skipExtract = c.structuredMode && c.hasRun;

    final graph = LayoutBuilder(builder: (context, constraints) {
      final narrow = constraints.maxWidth < 640;
      final extract = _NodeCard(spec: _extract, controller: c, note: skipExtract ? 'skipped: structured input' : null);
      final solveColumn = Column(
        children: [
          _NodeCard(spec: _solve, controller: c),
          _LoopConnector(controller: c, maxRelaxations: widget.maxRelaxations),
          _NodeCard(spec: _relax, controller: c),
        ],
      );
      final explain = _NodeCard(spec: _explain, controller: c);
      if (narrow) {
        return Column(children: [extract, const _Arrow(down: true), solveColumn, const _Arrow(down: true), explain]);
      }
      return Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(child: extract),
          const Padding(padding: EdgeInsets.only(top: 34), child: _Arrow()),
          Expanded(child: solveColumn),
          const Padding(padding: EdgeInsets.only(top: 34), child: _Arrow()),
          Expanded(child: explain),
        ],
      );
    });

    return SectionCard(
      title: 'Agent pipeline (LangGraph)',
      subtitle: 'Live state of every node. The solve → relax edge is the conditional loop.',
      icon: Icons.account_tree_outlined,
      trailing: c.hasRun
          ? StatusChip(
              c.running ? 'running ${formatMs(c.stopwatch.elapsedMilliseconds.toDouble())}' : 'finished',
              color: c.running ? theme.colorScheme.primary : (c.error == null ? goodColor(context) : badColor(context)),
              icon: c.running ? Icons.timelapse : (c.error == null ? Icons.check : Icons.error_outline),
            )
          : null,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          graph,
          const SizedBox(height: 12),
          Container(
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: theme.colorScheme.surfaceContainerHighest.withValues(alpha: 0.5),
              borderRadius: BorderRadius.circular(10),
            ),
            child: Row(
              children: [
                Icon(Icons.alt_route, size: 18, color: theme.colorScheme.onSurfaceVariant),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    route == null
                        ? 'Routing decision after each solve will appear here.'
                        : 'Last routing decision: ${route.decision} — ${route.reason}',
                    style: theme.textTheme.bodyMedium,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _NodeCard extends StatelessWidget {
  const _NodeCard({required this.spec, required this.controller, this.note});

  final _NodeSpec spec;
  final RunController controller;
  final String? note;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final status = controller.nodeStatus[spec.id]!;
    final runs = controller.nodeRuns[spec.id] ?? 0;
    final duration = controller.lastDurationMs[spec.id];
    final (border, background) = switch (status) {
      NodeStatus.idle => (scheme.outlineVariant, scheme.surface),
      NodeStatus.running => (scheme.primary, scheme.primaryContainer.withValues(alpha: 0.55)),
      NodeStatus.done => (goodColor(context), goodColor(context).withValues(alpha: 0.08)),
      NodeStatus.failed => (badColor(context), badColor(context).withValues(alpha: 0.08)),
    };
    final badge = switch (status) {
      NodeStatus.running => const SizedBox.square(dimension: 16, child: CircularProgressIndicator(strokeWidth: 2)),
      NodeStatus.done => Icon(Icons.check_circle, size: 18, color: goodColor(context)),
      NodeStatus.failed => Icon(Icons.cancel, size: 18, color: badColor(context)),
      NodeStatus.idle => Icon(Icons.radio_button_unchecked, size: 18, color: scheme.outline),
    };

    return AnimatedContainer(
      duration: const Duration(milliseconds: 250),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: background,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: border, width: status == NodeStatus.running ? 2 : 1),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(spec.icon, size: 18, color: scheme.primary),
              const SizedBox(width: 6),
              Expanded(child: Text(spec.title, style: theme.textTheme.titleSmall)),
              if (runs > 1) ...[
                StatusChip('×$runs', color: scheme.tertiary),
                const SizedBox(width: 6),
              ],
              badge,
            ],
          ),
          const SizedBox(height: 6),
          Text(spec.subtitle, style: theme.textTheme.bodySmall?.copyWith(color: scheme.onSurfaceVariant)),
          const SizedBox(height: 6),
          Text(
            note ?? (duration == null ? ' ' : 'last run ${formatMs(duration)}'),
            style: theme.textTheme.labelSmall?.copyWith(color: scheme.onSurfaceVariant),
          ),
        ],
      ),
    );
  }
}

class _LoopConnector extends StatelessWidget {
  const _LoopConnector({required this.controller, required this.maxRelaxations});

  final RunController controller;
  final int maxRelaxations;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final used = controller.relaxationsUsed;
    final active = controller.lastRoute?.decision == 'relax';
    final color = active ? theme.colorScheme.tertiary : theme.colorScheme.outline;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(Icons.swap_vert, color: color),
          const SizedBox(width: 6),
          Flexible(
            child: Text(
              'if INFEASIBLE · $used/$maxRelaxations relaxations',
              style: theme.textTheme.labelSmall?.copyWith(color: color),
              textAlign: TextAlign.center,
            ),
          ),
        ],
      ),
    );
  }
}

class _Arrow extends StatelessWidget {
  const _Arrow({this.down = false});

  final bool down;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.all(4),
        child: Icon(down ? Icons.arrow_downward : Icons.arrow_forward,
            color: Theme.of(context).colorScheme.outline),
      );
}
