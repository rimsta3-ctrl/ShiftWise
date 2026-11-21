import 'package:material_ui/material_ui.dart';

import '../api/models.dart';
import '../state/run_controller.dart';
import '../widgets/common.dart';
import '../widgets/event_timeline.dart';
import '../widgets/pipeline_view.dart';
import '../widgets/request_panel.dart';
import '../widgets/result_view.dart';
import '../widgets/schedule_grid.dart';

class RunScreen extends StatelessWidget {
  const RunScreen({super.key, required this.controller, required this.config});

  final RunController controller;
  final AgentConfig? config;

  // Keep the typed request and the timeline scroll position when the layout switches columns
  static final _requestKey = GlobalKey();
  static final _timelineKey = GlobalKey();

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: controller,
      builder: (context, _) {
        final request = RequestPanel(
            key: _requestKey, controller: controller, llmAvailable: config?.llmKeyConfigured ?? true);
        final configCard = _ConfigCard(config: config);
        final pipeline = PipelineView(controller: controller, maxRelaxations: config?.maxRelaxations ?? 6);
        final live = TwoColumns(
          breakpoint: 1000,
          left: EventTimeline(key: _timelineKey, controller: controller),
          right: SectionCard(
            title: 'Constraints',
            subtitle: 'What the extractor understood, and what the relaxation loop changed',
            icon: Icons.rule,
            child: ConstraintDiff(original: controller.extracted, current: controller.current),
          ),
        );
        final results = ResultView(controller: controller);

        return LayoutBuilder(builder: (context, constraints) {
          final wide = constraints.maxWidth >= 1250;
          return SingleChildScrollView(
            padding: const EdgeInsets.all(16),
            child: wide
                ? Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      SizedBox(width: 400, child: Column(children: [request, const SizedBox(height: 16), configCard])),
                      const SizedBox(width: 16),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.stretch,
                          children: [pipeline, const SizedBox(height: 16), live, const SizedBox(height: 16), results],
                        ),
                      ),
                    ],
                  )
                : Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      request,
                      const SizedBox(height: 16),
                      pipeline,
                      const SizedBox(height: 16),
                      live,
                      const SizedBox(height: 16),
                      results,
                      const SizedBox(height: 16),
                      configCard,
                    ],
                  ),
          );
        });
      },
    );
  }
}

class _ConfigCard extends StatelessWidget {
  const _ConfigCard({required this.config});

  final AgentConfig? config;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final c = config;
    Widget line(String label, String value) => Padding(
          padding: const EdgeInsets.symmetric(vertical: 3),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SizedBox(width: 150, child: Text(label, style: theme.textTheme.bodySmall)),
              Expanded(child: Text(value, style: theme.textTheme.bodySmall?.copyWith(fontWeight: FontWeight.w600))),
            ],
          ),
        );
    return SectionCard(
      title: 'Agent configuration',
      subtitle: 'Read from GET /config',
      icon: Icons.settings_outlined,
      child: c == null
          ? Text('API not reachable.', style: theme.textTheme.bodySmall)
          : Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                line('LLM model', c.model),
                line('Gemini key on server', c.llmKeyConfigured ? 'configured' : 'missing'),
                line('Extraction attempts', '${c.maxExtractionAttempts} (validation error fed back)'),
                line('CP-SAT time limit', '${c.solverTimeLimitS.toStringAsFixed(0)} s per solve'),
                line('Max relaxations', '${c.maxRelaxations}'),
                const SizedBox(height: 8),
                Text('Relaxation order (least harmful first)', style: theme.textTheme.labelLarge),
                for (final (i, step) in c.relaxationOrder.indexed)
                  Padding(
                    padding: const EdgeInsets.only(top: 2),
                    child: Text('${i + 1}. $step', style: theme.textTheme.bodySmall),
                  ),
              ],
            ),
    );
  }
}
