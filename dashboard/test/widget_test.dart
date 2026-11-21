import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';
import 'package:shiftwise_dashboard/api/client.dart';
import 'package:shiftwise_dashboard/api/models.dart';
import 'package:shiftwise_dashboard/main.dart';
import 'package:shiftwise_dashboard/widgets/request_panel.dart';

/// Events recorded from the real backend (POST /solve/stream), so the Dart side is tested
/// against the actual wire format.
List<Map<String, dynamic>> recordedRun() =>
    (jsonDecode(File('test/fixtures/infeasible_run.json').readAsStringSync()) as List).cast<Map<String, dynamic>>();

class FakeApi extends ApiClient {
  FakeApi() : super('http://fake');

  ScheduleProblem? lastProblem;

  @override
  Future<AgentConfig> config() async => AgentConfig.fromJson({
        'model': 'gemini-test',
        'llm_key_configured': false,
        'solver_time_limit_s': 10.0,
        'max_relaxations': 6,
        'max_extraction_attempts': 3,
        'relaxation_order': ['a', 'b', 'c', 'd'],
        'defaults': const ScheduleProblem(employees: ['Employee 1']).toJson(),
      });

  @override
  Future<Map<String, dynamic>> evaluation() async =>
      {'solver_benchmark': null, 'relaxation_benchmark': null, 'llm_eval': null, 'llm_cases': []};

  @override
  Stream<AgentEvent> solveStream(ScheduleProblem problem, {bool llmExplanation = false}) {
    lastProblem = problem;
    return Stream.fromIterable(recordedRun().map(AgentEvent.new));
  }
}

void main() {
  test('RunResult parses the backend result event', () {
    final result = RunResult.fromJson(recordedRun().last);
    expect(result.result.status, 'OPTIMAL');
    expect(result.relaxations, hasLength(4));
    expect(result.originalProblem.unavailable, [const Unavailability('Sara', 0)]);
    expect(result.problem.unavailable, isEmpty);
    expect(result.violations, isEmpty);
    expect(result.result.assignedShifts, result.requiredShifts);
  });

  test('decodeSse splits events and survives chunk boundaries inside UTF-8 characters', () async {
    final body = utf8.encode('data: {"type":"start","t_ms":1}\n\ndata: {"type":"error","detail":"congé"}\n\n');
    final chunks = [body.sublist(0, 10), body.sublist(10, body.length - 6), body.sublist(body.length - 6)];
    final events = await decodeSse(Stream.fromIterable(chunks)).toList();
    expect(events.map((e) => e['type']), ['start', 'error']);
    expect(events.last['detail'], 'congé');
  });

  test('parseUnavailability accepts day names and indexes, rejects unknown people', () {
    expect(parseUnavailability('Sara: Mon, tue; Ali: 4', ['Sara', 'Ali']),
        [const Unavailability('Sara', 0), const Unavailability('Sara', 1), const Unavailability('Ali', 4)]);
    expect(() => parseUnavailability('Ghost: Mon', ['Sara']), throwsFormatException);
    expect(() => parseUnavailability('Sara: someday', ['Sara']), throwsFormatException);
  });

  for (final (name, size) in [('wide', const Size(1600, 1400)), ('narrow', const Size(420, 900))]) {
    testWidgets('structured run renders the whole pipeline ($name layout)', (tester) async {
      tester.view.physicalSize = size;
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);

      final api = FakeApi();
      await tester.pumpWidget(ShiftWiseApp(api: api));
      await tester.pump();
      expect(find.textContaining('API connected'), findsOneWidget);

      await tester.tap(find.text('Structured'));
      await tester.pump();
      await tester.ensureVisible(find.text('Run the agent'));
      await tester.tap(find.text('Run the agent'));
      for (var i = 0; i < 5; i++) {
        await tester.pump(const Duration(milliseconds: 50));
      }

      expect(api.lastProblem?.employees, hasLength(6));
      expect(find.text('OPTIMAL'), findsWidgets);
      expect(find.text('0 violations'), findsOneWidget);
      // The concession is listed, and the overridden day-off is flagged in the schedule legend
      expect(find.textContaining('3. Ignored the unavailability of Sara'), findsOneWidget);
      expect(find.text('unavailability ignored'), findsOneWidget);
      expect(find.text('Schedule'), findsOneWidget);
      expect(find.textContaining('29 events received'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  }
}
