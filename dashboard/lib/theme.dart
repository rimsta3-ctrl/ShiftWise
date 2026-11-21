import 'package:material_ui/material_ui.dart';

const _seed = Color(0xFF2F5DA8);

ThemeData buildTheme(Brightness brightness) => ThemeData(
      colorSchemeSeed: _seed,
      brightness: brightness,
      visualDensity: VisualDensity.standard,
      cardTheme: const CardThemeData(margin: EdgeInsets.zero, elevation: 0),
    );

bool _isDark(BuildContext context) => Theme.of(context).brightness == Brightness.dark;

/// Stable, readable colour per shift (known names first, then a palette by position).
Color shiftColor(BuildContext context, String shift, List<String> allShifts) {
  final dark = _isDark(context);
  const known = {
    'morning': (Color(0xFFF2B33D), Color(0xFFD9A034)),
    'early': (Color(0xFFE9D66B), Color(0xFFC9B84F)),
    'day': (Color(0xFFF2B33D), Color(0xFFD9A034)),
    'afternoon': (Color(0xFF2A9D8F), Color(0xFF3FB5A6)),
    'evening': (Color(0xFF8E6CC9), Color(0xFFA68BDB)),
    'night': (Color(0xFF3D4FA8), Color(0xFF7A8BE0)),
  };
  final hit = known[shift.toLowerCase()];
  if (hit != null) return dark ? hit.$2 : hit.$1;
  const palette = [Color(0xFFD1495B), Color(0xFF00798C), Color(0xFFEDAE49), Color(0xFF66A182), Color(0xFF8E6CC9)];
  return palette[allShifts.indexOf(shift).clamp(0, palette.length - 1)];
}

Color onColor(Color background) =>
    ThemeData.estimateBrightnessForColor(background) == Brightness.dark ? Colors.white : const Color(0xFF1B1B1F);

/// Short label that fits in a grid cell; the legend shows the full name.
String shiftAbbrev(String shift) => switch (shift.toLowerCase()) {
      'morning' => 'AM',
      'afternoon' => 'PM',
      'night' => 'Night',
      'evening' => 'Eve',
      final s when s.length <= 5 => shift,
      _ => shift.substring(0, 4),
    };

Color statusColor(BuildContext context, String? status) {
  final dark = _isDark(context);
  return switch (status) {
    'OPTIMAL' => dark ? const Color(0xFF6FD08C) : const Color(0xFF1E7B34),
    'FEASIBLE' => dark ? const Color(0xFF4DB6AC) : const Color(0xFF00796B),
    'INFEASIBLE' => dark ? const Color(0xFFEF9A9A) : const Color(0xFFC62828),
    'UNKNOWN' => dark ? const Color(0xFFFFB74D) : const Color(0xFFB26A00),
    _ => Theme.of(context).colorScheme.onSurfaceVariant,
  };
}

Color goodColor(BuildContext context) => statusColor(context, 'OPTIMAL');
Color badColor(BuildContext context) => statusColor(context, 'INFEASIBLE');
Color warnColor(BuildContext context) => statusColor(context, 'UNKNOWN');
