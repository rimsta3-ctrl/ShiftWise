import 'package:material_ui/material_ui.dart';

import '../api/models.dart';
import '../theme.dart';
import '../widgets/common.dart';

class _Block {
  const _Block(this.icon, this.title, this.file, this.points);

  final IconData icon;
  final String title;
  final String file;
  final List<String> points;
}

const _blocks = [
  _Block(Icons.translate, 'Extract', 'extractor.py', [
    'Gemini, through LangChain structured output, turns the text into a ScheduleProblem.',
    'Pydantic validates it: duplicate names, unknown employees, days outside the horizon are rejected.',
    'On a validation error the message is fed back to the model; 3 attempts, then a 422.',
    'Network errors (503, quota) are not validation errors: they surface as a 503, not as feedback.',
  ]),
  _Block(Icons.memory, 'Solve', 'scheduler.py', [
    'One boolean per (employee, day, shift).',
    'Hard constraints: one shift per day, exact staffing, unavailability, max consecutive days, '
        'no morning right after a night.',
    'Objective: minimize the gap between the most and least loaded employee.',
    'Statuses: OPTIMAL (proven best), FEASIBLE (valid, not proven best), INFEASIBLE (proven impossible), '
        'UNKNOWN (time limit, no answer).',
  ]),
  _Block(Icons.alt_route, 'Route (conditional edge)', 'graph.py', [
    'Schedule found → explain.',
    'UNKNOWN → explain: a timeout is not a proof of infeasibility, so nothing is relaxed.',
    'INFEASIBLE and the cap is reached, or nothing is left to relax → explain.',
    'INFEASIBLE otherwise → relax, then solve again. This is the agentic loop.',
  ]),
  _Block(Icons.tune, 'Relax', 'graph.py', [
    'Loosens exactly one constraint per pass, least harmful first, and logs the concession.',
    'Deterministic and testable, but a heuristic: it does not know which constraint causes the conflict.',
  ]),
  _Block(Icons.chat_bubble_outline, 'Explain', 'graph.py', [
    'The LLM narrates using only the schedule and the list of concessions.',
    'If the call fails, a deterministic template is used, so the schedule is never lost.',
  ]),
  _Block(Icons.shield_outlined, 'Verify', 'validator.py', [
    'Re-checks every schedule against every hard constraint without using the CP-SAT model.',
    'The same checker scores the greedy and LLM-only baselines in the evaluation.',
  ]),
];

class AboutScreen extends StatelessWidget {
  const AboutScreen({super.key, required this.config});

  final AgentConfig? config;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          SectionCard(
            title: 'Design principle',
            icon: Icons.lightbulb_outline,
            child: Text(
              'LLMs are good at language and bad at guaranteeing constraints; solvers are the opposite. '
              'So the LLM only translates the request and narrates the outcome. The solver alone decides the '
              'schedule, and the LLM never edits it.',
              style: theme.textTheme.bodyLarge,
            ),
          ),
          const SizedBox(height: 16),
          Wrap(
            spacing: 16,
            runSpacing: 16,
            children: [
              for (final b in _blocks)
                SizedBox(
                  width: 420,
                  child: SectionCard(
                    title: b.title,
                    subtitle: b.file,
                    icon: b.icon,
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        for (final p in b.points)
                          Padding(
                            padding: const EdgeInsets.only(bottom: 4),
                            child: Text('• $p', style: theme.textTheme.bodyMedium),
                          ),
                      ],
                    ),
                  ),
                ),
            ],
          ),
          const SizedBox(height: 16),
          SectionCard(
            title: 'What is guaranteed, and what is not',
            icon: Icons.policy_outlined,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _Claim(ok: true, text: 'Every returned schedule satisfies the extracted problem (checked independently).'),
                _Claim(ok: true, text: 'Every concession made to reach a schedule is listed.'),
                _Claim(
                  ok: false,
                  text: 'That the extracted problem matches what the user meant. That is why the API returns it '
                      'and why the evaluation compares schedules with gold (expected) problems.',
                ),
                _Claim(ok: false, text: 'That the relaxation is minimal (measured in the Evaluation tab).'),
              ],
            ),
          ),
          if (config != null) ...[
            const SizedBox(height: 16),
            SectionCard(
              title: 'How this dashboard sees the agent',
              icon: Icons.podcasts,
              child: Text(
                'POST /plan/stream (or /solve/stream for structured input) runs the LangGraph agent with an '
                'on_event hook. Every node start and end, every extraction attempt and every routing decision is '
                'pushed as a Server-Sent Event, and the final event carries the schedule and the independent '
                'check. Current model: ${config!.model}; CP-SAT limit '
                '${config!.solverTimeLimitS.toStringAsFixed(0)} s; up to ${config!.maxRelaxations} relaxations.',
                style: theme.textTheme.bodyMedium,
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _Claim extends StatelessWidget {
  const _Claim({required this.ok, required this.text});

  final bool ok;
  final String text;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 3),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(ok ? Icons.check_circle_outline : Icons.remove_circle_outline,
                size: 18, color: ok ? goodColor(context) : warnColor(context)),
            const SizedBox(width: 8),
            Expanded(child: Text(text, style: Theme.of(context).textTheme.bodyMedium)),
          ],
        ),
      );
}
