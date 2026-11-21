import 'dart:async';

import 'package:flutter/foundation.dart';

import '../api/client.dart';
import '../api/models.dart';

enum NodeStatus { idle, running, done, failed }

const pipelineNodes = ['extract', 'solve', 'relax', 'explain'];

/// Turns the agent's event stream into state the widgets can render.
class RunController extends ChangeNotifier {
  RunController(this.api);

  final ApiClient api;

  final List<AgentEvent> events = [];
  final Map<String, NodeStatus> nodeStatus = {for (final n in pipelineNodes) n: NodeStatus.idle};
  final Map<String, int> nodeRuns = {for (final n in pipelineNodes) n: 0};
  final Map<String, double> lastDurationMs = {};
  final Stopwatch stopwatch = Stopwatch();
  StreamSubscription<AgentEvent>? _subscription;

  bool running = false;
  bool structuredMode = false;
  String? requestText;
  ScheduleProblem? extracted;
  ScheduleProblem? current;
  RunResult? result;
  AgentEvent? lastRoute;
  String? error;
  int? errorStatus;

  bool get hasRun => events.isNotEmpty || running || error != null;
  int get relaxationsUsed => nodeRuns['relax'] ?? 0;

  void runText(String text) {
    structuredMode = false;
    requestText = text;
    _start(api.planStream(text));
  }

  void runProblem(ScheduleProblem problem, {bool llmExplanation = false}) {
    structuredMode = true;
    requestText = null;
    _start(api.solveStream(problem, llmExplanation: llmExplanation));
  }

  void cancel() {
    if (!running) return;
    _subscription?.cancel();
    error = 'Cancelled by the user.';
    _markRunningNodesFailed();
    _finish();
  }

  void _start(Stream<AgentEvent> stream) {
    _subscription?.cancel();
    events.clear();
    for (final n in pipelineNodes) {
      nodeStatus[n] = NodeStatus.idle;
      nodeRuns[n] = 0;
    }
    lastDurationMs.clear();
    extracted = null;
    current = null;
    result = null;
    lastRoute = null;
    error = null;
    errorStatus = null;
    running = true;
    stopwatch
      ..reset()
      ..start();
    notifyListeners();

    _subscription = stream.listen(
      _onEvent,
      onError: (Object e) {
        error = e is ApiException ? e.message : 'Cannot reach the API at $apiUrl ($e)';
        errorStatus = e is ApiException ? e.statusCode : null;
        _markRunningNodesFailed();
        _finish();
      },
      onDone: _finish,
    );
  }

  void _finish() {
    if (!running) return;
    running = false;
    stopwatch.stop();
    notifyListeners();
  }

  void _markRunningNodesFailed() {
    for (final n in pipelineNodes) {
      if (nodeStatus[n] == NodeStatus.running) nodeStatus[n] = NodeStatus.failed;
    }
  }

  void _onEvent(AgentEvent event) {
    events.add(event);
    switch (event.type) {
      case 'node_start':
        nodeStatus[event.node!] = NodeStatus.running;
      case 'node_end':
        final node = event.node!;
        nodeStatus[node] = NodeStatus.done;
        nodeRuns[node] = (nodeRuns[node] ?? 0) + 1;
        lastDurationMs[node] = event.durationMs ?? 0;
        if (node == 'extract') {
          extracted = event.problem;
          current = event.problem;
        } else if (node == 'relax') {
          current = event.problem;
        }
      case 'route':
        lastRoute = event;
      case 'result':
        final r = RunResult.fromJson(event.raw);
        result = r;
        extracted = r.originalProblem;
        current = r.problem;
      case 'error':
        error = event.detail;
        errorStatus = int.tryParse(event.status ?? '');
        _markRunningNodesFailed();
    }
    notifyListeners();
  }

  @override
  void dispose() {
    _subscription?.cancel();
    super.dispose();
  }
}
