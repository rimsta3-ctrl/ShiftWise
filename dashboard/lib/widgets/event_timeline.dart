import 'dart:convert';

import 'package:material_ui/material_ui.dart';

import '../api/models.dart';
import '../state/run_controller.dart';
import '../theme.dart';
import 'common.dart';

class _Line {
  const _Line(this.icon, this.color, this.title, {this.subtitle, this.details, this.dim = false});

  final IconData icon;
  final Color color;
  final String title;
  final String? subtitle;
  final Object? details;
  final bool dim;
}

String _summary(ScheduleProblem? p) => p == null
    ? ''
    : '${p.employees.length} employees · ${p.numDays} days · ${p.shifts.length} shifts · '
        '${p.minStaffPerShift}/shift · max ${p.maxConsecutiveDays} in a row · '
        '${p.unavailable.length} unavailability · rest rule ${p.noMorningAfterNight ? 'on' : 'off'}';

_Line _describe(BuildContext context, AgentEvent e) {
  final scheme = Theme.of(context).colorScheme;
  final muted = scheme.onSurfaceVariant;
  switch (e.type) {
    case 'start':
      return _Line(Icons.play_arrow, scheme.primary, 'Request received by the API');
    case 'node_start':
      return _Line(Icons.subdirectory_arrow_right, muted, '${e.node} started', dim: true);
    case 'extract_attempt':
      return e.error == null
          ? _Line(Icons.verified, goodColor(context), 'Extraction attempt ${e.raw['attempt']}: valid ScheduleProblem')
          : _Line(Icons.replay, warnColor(context), 'Extraction attempt ${e.raw['attempt']} rejected, error sent back to the LLM',
              subtitle: e.error!.split('\n').take(3).join(' '));
    case 'node_end':
      final took = formatMs(e.durationMs ?? 0);
      switch (e.node) {
        case 'extract':
          return _Line(Icons.translate, scheme.primary, 'extract finished in $took',
              subtitle: _summary(e.problem), details: e.raw['problem']);
        case 'solve':
          final status = e.status ?? '?';
          final extra = status == 'OPTIMAL' || status == 'FEASIBLE'
              ? ' · gap ${e.raw['shift_gap']} · ${e.raw['assigned_shifts']} shifts assigned'
              : '';
          return _Line(Icons.memory, statusColor(context, status),
              'CP-SAT → $status in ${(e.raw['solve_time_s'] as num).toStringAsFixed(3)} s$extra',
              subtitle: 'node time $took');
        case 'relax':
          return _Line(Icons.tune, scheme.tertiary, 'relax: ${e.note}',
              subtitle: _summary(e.problem), details: e.raw['problem']);
        case 'explain':
          return _Line(Icons.chat_bubble_outline, scheme.primary, 'explain finished in $took',
              subtitle: e.raw['explanation']?.toString().split('\n').first);
      }
      return _Line(Icons.circle, muted, '${e.node} finished in $took');
    case 'route':
      return _Line(Icons.alt_route, e.decision == 'relax' ? scheme.tertiary : scheme.secondary,
          'route → ${e.decision}', subtitle: e.reason);
    case 'result':
      final violations = (e.raw['verification']?['violations'] as List?)?.length ?? 0;
      final checked = e.raw['verification']?['checked'] == true;
      return _Line(
        checked ? Icons.shield_outlined : Icons.info_outline,
        checked && violations == 0 ? goodColor(context) : warnColor(context),
        checked ? 'Done · independent check: $violations violation(s)' : 'Done · no schedule to check',
      );
    case 'error':
      return _Line(Icons.error_outline, badColor(context), 'Error ${e.status ?? ''}', subtitle: e.detail);
  }
  return _Line(Icons.circle_outlined, muted, e.type, details: e.raw);
}

class EventTimeline extends StatefulWidget {
  const EventTimeline({super.key, required this.controller, this.height = 420});

  final RunController controller;
  final double height;

  @override
  State<EventTimeline> createState() => _EventTimelineState();
}

class _EventTimelineState extends State<EventTimeline> {
  final _scroll = ScrollController();
  int _seen = 0;
  bool _showNodeStarts = true;

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final events = widget.controller.events
        .where((e) => _showNodeStarts || e.type != 'node_start')
        .toList(growable: false);

    // Follow the newest event while the run is live
    if (widget.controller.events.length != _seen) {
      _seen = widget.controller.events.length;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (_scroll.hasClients) {
          _scroll.animateTo(_scroll.position.maxScrollExtent,
              duration: const Duration(milliseconds: 200), curve: Curves.easeOut);
        }
      });
    }

    return SectionCard(
      title: 'Event stream',
      subtitle: '${widget.controller.events.length} events received (Server-Sent Events)',
      icon: Icons.receipt_long_outlined,
      trailing: FilterChip(
        label: const Text('node starts'),
        selected: _showNodeStarts,
        onSelected: (v) => setState(() => _showNodeStarts = v),
      ),
      child: SizedBox(
        height: widget.height,
        child: events.isEmpty
            ? Center(
                child: Text('Run a request to watch the agent work.',
                    style: theme.textTheme.bodyMedium?.copyWith(color: theme.colorScheme.onSurfaceVariant)),
              )
            : ListView.separated(
                controller: _scroll,
                itemCount: events.length,
                separatorBuilder: (context, index) => const Divider(height: 1),
                itemBuilder: (context, i) => _EventRow(event: events[i], line: _describe(context, events[i])),
              ),
      ),
    );
  }
}

class _EventRow extends StatelessWidget {
  const _EventRow({required this.event, required this.line});

  final AgentEvent event;
  final _Line line;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final time = Text(
      '+${event.tMs.toStringAsFixed(0).padLeft(6)} ms',
      style: theme.textTheme.labelSmall?.copyWith(fontFamily: 'monospace', color: theme.colorScheme.onSurfaceVariant),
    );
    final title = Text(
      line.title,
      style: (line.dim ? theme.textTheme.bodySmall : theme.textTheme.bodyMedium)
          ?.copyWith(color: line.dim ? theme.colorScheme.onSurfaceVariant : null),
    );
    final subtitle = line.subtitle == null
        ? null
        : Text(line.subtitle!,
            style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.onSurfaceVariant),
            maxLines: 3,
            overflow: TextOverflow.ellipsis);
    final leading = Row(
      mainAxisSize: MainAxisSize.min,
      children: [time, const SizedBox(width: 8), Icon(line.icon, size: 18, color: line.color)],
    );

    if (line.details == null) {
      return ListTile(dense: true, leading: leading, title: title, subtitle: subtitle, minLeadingWidth: 0);
    }
    return ExpansionTile(
      dense: true,
      leading: leading,
      title: title,
      subtitle: subtitle,
      childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
      expandedCrossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Container(
          padding: const EdgeInsets.all(10),
          decoration: BoxDecoration(
            color: theme.colorScheme.surfaceContainerHighest,
            borderRadius: BorderRadius.circular(8),
          ),
          child: SelectableText(
            const JsonEncoder.withIndent('  ').convert(line.details),
            style: theme.textTheme.bodySmall?.copyWith(fontFamily: 'monospace'),
          ),
        ),
      ],
    );
  }
}
