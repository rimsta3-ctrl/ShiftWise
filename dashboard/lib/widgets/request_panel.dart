import 'package:material_ui/material_ui.dart';

import '../api/models.dart';
import '../state/run_controller.dart';
import 'common.dart';

const _textExamples = {
  'Feasible week':
      'Plan a week for 6 employees: Sara, Ali, Mona, Yassine, Leila and Omar. Every shift needs at least 1 person. '
          'Nobody works more than 4 days in a row. Sara can\'t work on Monday and Tuesday, and Ali is off on Friday.',
  'Infeasible → relaxation': 'Team: Sara, Ali, Mona, Yassine, Leila, Omar. 2 people per shift.',
  'Headcount only': '8 employees, 3 shifts per day, max 5 consecutive days, Sara doesn\'t work on Monday',
  'In French': 'Planning de la semaine pour Ali, Mona, Karim, Ines, Hedi, Salma et Rami. Personne ne travaille '
      'plus de 4 jours d\'affilée. Karim est en congé mercredi et jeudi.',
  'Impossible': 'Plan a week for Sara, Ali and Mona with one person on every shift.',
};

class _Preset {
  const _Preset(this.employees, this.days, this.staff, this.maxConsecutive, this.unavailable);

  final String employees;
  final int days;
  final int staff;
  final int maxConsecutive;
  final String unavailable;
}

const _structuredPresets = {
  'Infeasible: 6 people, 2/shift': _Preset('Sara, Ali, Mona, Yassine, Leila, Omar', 7, 2, 5, ''),
  'Feasible: 8 people, 2/shift': _Preset('Sara, Ali, Mona, Yassine, Leila, Omar, Nour, Karim', 7, 2, 5, 'Sara: Mon, Tue'),
  'Two weeks, 12 people': _Preset('Anna, Ben, Chloe, David, Emma, Farid, Gina, Hugo, Ines, Jad, Lina, Marc', 14, 2, 4,
      'Anna: 0, 7; Ben: Sat, Sun'),
  'Tight: 4 people, max 2 in a row': _Preset('Anna, Ben, Chloe, David', 7, 1, 2, ''),
};

const _dayPrefixes = {
  'mon': 0, 'tue': 1, 'wed': 2, 'thu': 3, 'fri': 4, 'sat': 5, 'sun': 6,
  'lun': 0, 'mar': 1, 'mer': 2, 'jeu': 3, 'ven': 4, 'sam': 5, 'dim': 6,
};

/// Parses "Sara: Mon, Tue; Ali: 4" (day names or 0-based indexes). Throws FormatException.
List<Unavailability> parseUnavailability(String text, List<String> employees) {
  final result = <Unavailability>[];
  for (final part in text.split(';').map((s) => s.trim()).where((s) => s.isNotEmpty)) {
    final pieces = part.split(':');
    if (pieces.length != 2) throw FormatException('"$part": expected "Name: days"');
    final name = pieces[0].trim();
    if (!employees.contains(name)) throw FormatException('"$name" is not in the employee list');
    for (final token in pieces[1].split(',').map((s) => s.trim().toLowerCase()).where((s) => s.isNotEmpty)) {
      final day = int.tryParse(token) ??
          (token.length >= 3 ? _dayPrefixes[token.substring(0, 3)] : null) ??
          (throw FormatException('"$token" is not a day name or a 0-based day index'));
      result.add(Unavailability(name, day));
    }
  }
  return result;
}

class RequestPanel extends StatefulWidget {
  const RequestPanel({super.key, required this.controller, required this.llmAvailable});

  final RunController controller;
  final bool llmAvailable;

  @override
  State<RequestPanel> createState() => _RequestPanelState();
}

class _RequestPanelState extends State<RequestPanel> {
  bool _structured = false;
  final _text = TextEditingController(text: _textExamples['Infeasible → relaxation']);
  final _employees = TextEditingController();
  final _shifts = TextEditingController(text: 'morning, afternoon, night');
  final _days = TextEditingController();
  final _staff = TextEditingController();
  final _maxConsecutive = TextEditingController();
  final _unavailable = TextEditingController();
  bool _rest = true;
  bool _llmExplanation = false;
  String? _formError;

  @override
  void initState() {
    super.initState();
    _applyPreset(_structuredPresets.values.first);
  }

  @override
  void didUpdateWidget(RequestPanel oldWidget) {
    super.didUpdateWidget(oldWidget);
    // A run started elsewhere (e.g. the ?demo=1 link) shows the matching input mode
    final c = widget.controller;
    if (c.running && c.structuredMode != _structured) _structured = c.structuredMode;
  }

  @override
  void dispose() {
    for (final c in [_text, _employees, _shifts, _days, _staff, _maxConsecutive, _unavailable]) {
      c.dispose();
    }
    super.dispose();
  }

  void _applyPreset(_Preset p) {
    _employees.text = p.employees;
    _days.text = '${p.days}';
    _staff.text = '${p.staff}';
    _maxConsecutive.text = '${p.maxConsecutive}';
    _unavailable.text = p.unavailable;
    _rest = true;
  }

  List<String> _list(TextEditingController c) =>
      c.text.split(',').map((s) => s.trim()).where((s) => s.isNotEmpty).toList();

  void _run() {
    final c = widget.controller;
    if (!_structured) {
      if (_text.text.trim().length < 3) return;
      c.runText(_text.text.trim());
      return;
    }
    try {
      final employees = _list(_employees);
      final shifts = _list(_shifts);
      int number(TextEditingController t, String label) =>
          int.tryParse(t.text.trim()) ?? (throw FormatException('$label must be a whole number'));
      if (employees.isEmpty) throw const FormatException('add at least one employee');
      if (shifts.isEmpty) throw const FormatException('add at least one shift');
      final problem = ScheduleProblem(
        employees: employees,
        shifts: shifts,
        numDays: number(_days, 'Days'),
        minStaffPerShift: number(_staff, 'Staff per shift'),
        maxConsecutiveDays: number(_maxConsecutive, 'Max consecutive days'),
        unavailable: parseUnavailability(_unavailable.text, employees),
        noMorningAfterNight: _rest,
      );
      setState(() => _formError = null);
      c.runProblem(problem, llmExplanation: _llmExplanation);
    } on FormatException catch (e) {
      setState(() => _formError = e.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final running = widget.controller.running;

    return SectionCard(
      title: 'Request',
      subtitle: _structured
          ? 'Structured input: skips the LLM extraction (works without Gemini).'
          : 'Plain language: the LLM extracts a ScheduleProblem first.',
      icon: Icons.edit_note,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          SegmentedButton<bool>(
            segments: const [
              ButtonSegment(value: false, label: Text('Plain language'), icon: Icon(Icons.chat_outlined)),
              ButtonSegment(value: true, label: Text('Structured'), icon: Icon(Icons.table_rows_outlined)),
            ],
            selected: {_structured},
            onSelectionChanged: running ? null : (s) => setState(() => _structured = s.first),
          ),
          const SizedBox(height: 12),
          if (!_structured) ..._textInputs(theme) else ..._structuredInputs(theme),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: FilledButton.icon(
                  onPressed: running ? null : _run,
                  icon: const Icon(Icons.play_arrow),
                  label: Text(running ? 'Running…' : 'Run the agent'),
                ),
              ),
              if (running) ...[
                const SizedBox(width: 8),
                OutlinedButton(onPressed: widget.controller.cancel, child: const Text('Cancel')),
              ],
            ],
          ),
        ],
      ),
    );
  }

  List<Widget> _textInputs(ThemeData theme) => [
        if (!widget.llmAvailable)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Text(
              'No Gemini key is configured on the server: plain-language runs will fail. Use Structured mode.',
              style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.error),
            ),
          ),
        TextField(
          controller: _text,
          minLines: 4,
          maxLines: 8,
          maxLength: 2000,
          decoration: const InputDecoration(border: OutlineInputBorder(), labelText: 'Describe the staffing problem'),
        ),
        Wrap(
          spacing: 6,
          runSpacing: 6,
          children: [
            for (final entry in _textExamples.entries)
              ActionChip(label: Text(entry.key), onPressed: () => setState(() => _text.text = entry.value)),
          ],
        ),
      ];

  List<Widget> _structuredInputs(ThemeData theme) {
    InputDecoration deco(String label, {String? helper}) =>
        InputDecoration(border: const OutlineInputBorder(), labelText: label, helperText: helper, isDense: true);
    Widget number(TextEditingController c, String label) => Expanded(
          child: TextField(controller: c, keyboardType: TextInputType.number, decoration: deco(label)),
        );
    return [
      Wrap(
        spacing: 6,
        runSpacing: 6,
        children: [
          for (final entry in _structuredPresets.entries)
            ActionChip(label: Text(entry.key), onPressed: () => setState(() => _applyPreset(entry.value))),
        ],
      ),
      const SizedBox(height: 12),
      TextField(controller: _employees, decoration: deco('Employees', helper: 'comma separated')),
      const SizedBox(height: 10),
      TextField(controller: _shifts, decoration: deco('Shifts', helper: 'comma separated')),
      const SizedBox(height: 10),
      Row(children: [
        number(_days, 'Days'),
        const SizedBox(width: 8),
        number(_staff, 'Staff/shift'),
        const SizedBox(width: 8),
        number(_maxConsecutive, 'Max in a row'),
      ]),
      const SizedBox(height: 10),
      TextField(
        controller: _unavailable,
        decoration: deco('Unavailability', helper: 'e.g. "Sara: Mon, Tue; Ali: 4" (names or 0-based days)'),
      ),
      SwitchListTile(
        contentPadding: EdgeInsets.zero,
        title: const Text('No morning shift right after a night shift'),
        value: _rest,
        onChanged: (v) => setState(() => _rest = v),
      ),
      SwitchListTile(
        contentPadding: EdgeInsets.zero,
        title: const Text('Narrate with the LLM'),
        subtitle: const Text('Off: deterministic template, no API call'),
        value: _llmExplanation,
        onChanged: widget.llmAvailable ? (v) => setState(() => _llmExplanation = v) : null,
      ),
      if (_formError != null)
        Text(_formError!, style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.error)),
    ];
  }
}

/// The first structured preset as a problem: 6 people, 2 per shift (needs relaxation).
final demoProblem = ScheduleProblem(
  employees: _structuredPresets.values.first.employees.split(',').map((s) => s.trim()).toList(),
  minStaffPerShift: _structuredPresets.values.first.staff,
);
