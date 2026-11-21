import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import 'models.dart';
import 'streaming_client.dart';

/// Backend URL, override with: flutter run --dart-define=API_URL=http://host:port
const apiUrl = String.fromEnvironment('API_URL', defaultValue: 'http://localhost:8000');

class ApiException implements Exception {
  const ApiException(this.statusCode, this.message);

  final int? statusCode;
  final String message;

  @override
  String toString() => statusCode == null ? message : 'HTTP $statusCode: $message';
}

/// Decodes a text/event-stream body into the JSON payload of each `data:` event.
Stream<Map<String, dynamic>> decodeSse(Stream<List<int>> bytes) async* {
  final data = StringBuffer();
  await for (final line in bytes.transform(utf8.decoder).transform(const LineSplitter())) {
    if (line.startsWith('data:')) {
      if (data.isNotEmpty) data.write('\n');
      data.write(line.substring(5).trimLeft());
    } else if (line.isEmpty && data.isNotEmpty) {
      yield jsonDecode(data.toString()) as Map<String, dynamic>;
      data.clear();
    }
  }
  if (data.isNotEmpty) yield jsonDecode(data.toString()) as Map<String, dynamic>;
}

class ApiClient {
  ApiClient([this.baseUrl = apiUrl]);

  final String baseUrl;

  Uri _uri(String path) => Uri.parse('$baseUrl$path');

  Future<Map<String, dynamic>> _getJson(String path, {Duration timeout = const Duration(seconds: 8)}) async {
    final response = await http.get(_uri(path)).timeout(timeout);
    if (response.statusCode != 200) throw ApiException(response.statusCode, _detail(response.body));
    return jsonDecode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
  }

  Future<AgentConfig> config() async => AgentConfig.fromJson(await _getJson('/config'));

  Future<Map<String, dynamic>> evaluation() => _getJson('/evaluation', timeout: const Duration(seconds: 20));

  /// Natural-language request: the LLM extracts the problem, then the agent runs.
  Stream<AgentEvent> planStream(String request) => _events('/plan/stream', {'request': request});

  /// Structured problem: extraction is skipped, so no LLM is needed unless [llmExplanation].
  Stream<AgentEvent> solveStream(ScheduleProblem problem, {bool llmExplanation = false}) =>
      _events('/solve/stream', {'problem': problem.toJson(), 'llm_explanation': llmExplanation});

  Stream<AgentEvent> _events(String path, Map<String, dynamic> body) async* {
    final client = createStreamingClient();
    try {
      final request = http.Request('POST', _uri(path))
        ..headers['Content-Type'] = 'application/json'
        ..body = jsonEncode(body);
      final response = await client.send(request);
      if (response.statusCode != 200) {
        throw ApiException(response.statusCode, _detail(await response.stream.bytesToString()));
      }
      await for (final event in decodeSse(response.stream)) {
        yield AgentEvent(event);
      }
    } finally {
      client.close();
    }
  }

  static String _detail(String body) {
    try {
      final detail = (jsonDecode(body) as Map<String, dynamic>)['detail'];
      if (detail is List) {
        return detail.map((d) => d is Map ? '${(d['loc'] as List?)?.join('.')}: ${d['msg']}' : '$d').join('; ');
      }
      return '$detail';
    } catch (_) {
      return body.isEmpty ? 'empty response' : body;
    }
  }
}
