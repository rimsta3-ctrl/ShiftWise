/// Dart mirrors of the backend's Pydantic models and of the agent's stream events.
library;

const dayNames = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

/// Same convention as the backend: Mon..Sun for a single week, D1..Dn beyond.
String dayLabel(int day, int numDays) => numDays <= 7 ? dayNames[day % 7] : 'D${day + 1}';

class Unavailability {
  const Unavailability(this.employee, this.day);

  final String employee;
  final int day;

  factory Unavailability.fromJson(Map<String, dynamic> json) =>
      Unavailability(json['employee'] as String, (json['day'] as num).toInt());

  Map<String, dynamic> toJson() => {'employee': employee, 'day': day};

  @override
  bool operator ==(Object other) => other is Unavailability && other.employee == employee && other.day == day;

  @override
  int get hashCode => Object.hash(employee, day);
}

class ScheduleProblem {
  const ScheduleProblem({
    required this.employees,
    this.numDays = 7,
    this.shifts = const ['morning', 'afternoon', 'night'],
    this.minStaffPerShift = 1,
    this.maxConsecutiveDays = 5,
    this.unavailable = const [],
    this.noMorningAfterNight = true,
  });

  final List<String> employees;
  final int numDays;
  final List<String> shifts;
  final int minStaffPerShift;
  final int maxConsecutiveDays;
  final List<Unavailability> unavailable;
  final bool noMorningAfterNight;

  int get requiredShifts => minStaffPerShift * shifts.length * numDays;

  factory ScheduleProblem.fromJson(Map<String, dynamic> json) => ScheduleProblem(
        employees: List<String>.from(json['employees'] as List),
        numDays: (json['num_days'] as num).toInt(),
        shifts: List<String>.from(json['shifts'] as List),
        minStaffPerShift: (json['min_staff_per_shift'] as num).toInt(),
        maxConsecutiveDays: (json['max_consecutive_days'] as num).toInt(),
        unavailable: [
          for (final u in json['unavailable'] as List) Unavailability.fromJson(u as Map<String, dynamic>),
        ],
        noMorningAfterNight: json['no_morning_after_night'] as bool,
      );

  Map<String, dynamic> toJson() => {
        'employees': employees,
        'num_days': numDays,
        'shifts': shifts,
        'min_staff_per_shift': minStaffPerShift,
        'max_consecutive_days': maxConsecutiveDays,
        'unavailable': [for (final u in unavailable) u.toJson()],
        'no_morning_after_night': noMorningAfterNight,
      };
}

class ScheduleResult {
  const ScheduleResult({
    required this.status,
    required this.assignments,
    required this.shiftGap,
    required this.solveTimeS,
  });

  final String status;

  /// employee -> {day index -> shift name}
  final Map<String, Map<int, String>> assignments;
  final int? shiftGap;
  final double solveTimeS;

  bool get hasSchedule => assignments.isNotEmpty;

  int get assignedShifts => assignments.values.fold(0, (sum, days) => sum + days.length);

  factory ScheduleResult.fromJson(Map<String, dynamic> json) {
    final raw = (json['assignments'] as Map?) ?? const {};
    return ScheduleResult(
      status: json['status'] as String,
      assignments: {
        for (final entry in raw.entries)
          entry.key as String: {
            for (final day in (entry.value as Map).entries) int.parse(day.key.toString()): day.value as String,
          },
      },
      shiftGap: (json['shift_gap'] as num?)?.toInt(),
      solveTimeS: (json['solve_time_s'] as num?)?.toDouble() ?? 0,
    );
  }
}

/// Final payload of a streamed run ({"type": "result", ...}).
class RunResult {
  const RunResult({
    required this.originalProblem,
    required this.problem,
    required this.result,
    required this.relaxations,
    required this.explanation,
    required this.explanationSource,
    required this.scheduleText,
    required this.requiredShifts,
    required this.verified,
    required this.violations,
    required this.totalMs,
  });

  final ScheduleProblem originalProblem;
  final ScheduleProblem problem;
  final ScheduleResult result;
  final List<String> relaxations;
  final String explanation;
  final String explanationSource;
  final String scheduleText;
  final int requiredShifts;
  final bool verified;
  final List<String> violations;
  final double totalMs;

  factory RunResult.fromJson(Map<String, dynamic> json) {
    final verification = json['verification'] as Map<String, dynamic>;
    return RunResult(
      originalProblem: ScheduleProblem.fromJson(json['original_problem'] as Map<String, dynamic>),
      problem: ScheduleProblem.fromJson(json['problem'] as Map<String, dynamic>),
      result: ScheduleResult.fromJson(json['result'] as Map<String, dynamic>),
      relaxations: List<String>.from(json['relaxations'] as List),
      explanation: json['explanation'] as String,
      explanationSource: json['explanation_source'] as String,
      scheduleText: json['schedule_text'] as String,
      requiredShifts: (json['required_shifts'] as num).toInt(),
      verified: verification['checked'] as bool,
      violations: List<String>.from(verification['violations'] as List),
      totalMs: (json['t_ms'] as num?)?.toDouble() ?? 0,
    );
  }
}

/// One Server-Sent Event from /plan/stream or /solve/stream.
class AgentEvent {
  const AgentEvent(this.raw);

  final Map<String, dynamic> raw;

  String get type => raw['type'] as String;
  double get tMs => (raw['t_ms'] as num?)?.toDouble() ?? 0;
  String? get node => raw['node'] as String?;
  double? get durationMs => (raw['duration_ms'] as num?)?.toDouble();
  String? get status => raw['status']?.toString();
  String? get decision => raw['decision'] as String?;
  String? get reason => raw['reason'] as String?;
  String? get note => raw['note'] as String?;
  String? get error => raw['error'] as String?;
  String? get detail => raw['detail']?.toString();

  ScheduleProblem? get problem {
    final p = raw['problem'];
    return p is Map<String, dynamic> ? ScheduleProblem.fromJson(p) : null;
  }
}

class AgentConfig {
  const AgentConfig({
    required this.model,
    required this.llmKeyConfigured,
    required this.solverTimeLimitS,
    required this.maxRelaxations,
    required this.maxExtractionAttempts,
    required this.relaxationOrder,
    required this.defaults,
  });

  final String model;
  final bool llmKeyConfigured;
  final double solverTimeLimitS;
  final int maxRelaxations;
  final int maxExtractionAttempts;
  final List<String> relaxationOrder;
  final ScheduleProblem defaults;

  factory AgentConfig.fromJson(Map<String, dynamic> json) => AgentConfig(
        model: json['model'] as String,
        llmKeyConfigured: json['llm_key_configured'] as bool,
        solverTimeLimitS: (json['solver_time_limit_s'] as num).toDouble(),
        maxRelaxations: (json['max_relaxations'] as num).toInt(),
        maxExtractionAttempts: (json['max_extraction_attempts'] as num).toInt(),
        relaxationOrder: List<String>.from(json['relaxation_order'] as List),
        defaults: ScheduleProblem.fromJson(json['defaults'] as Map<String, dynamic>),
      );
}
