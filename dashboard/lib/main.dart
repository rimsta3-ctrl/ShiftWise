import 'package:material_ui/material_ui.dart';

import 'api/client.dart';
import 'api/models.dart';
import 'screens/about_screen.dart';
import 'screens/evaluation_screen.dart';
import 'screens/run_screen.dart';
import 'state/run_controller.dart';
import 'theme.dart';
import 'widgets/common.dart';
import 'widgets/request_panel.dart' show demoProblem;

void main() => runApp(ShiftWiseApp(api: ApiClient()));

class ShiftWiseApp extends StatelessWidget {
  const ShiftWiseApp({super.key, required this.api});

  final ApiClient api;

  @override
  Widget build(BuildContext context) => MaterialApp(
        title: 'ShiftWise dashboard',
        debugShowCheckedModeBanner: false,
        theme: buildTheme(Brightness.light),
        darkTheme: buildTheme(Brightness.dark),
        home: HomeShell(api: api),
      );
}

class HomeShell extends StatefulWidget {
  const HomeShell({super.key, required this.api});

  final ApiClient api;

  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> {
  late final RunController _controller = RunController(widget.api);
  int _tab = 0;
  AgentConfig? _config;
  Object? _configError;
  bool _loadingConfig = true;

  @override
  void initState() {
    super.initState();
    // Shareable demo links: ?tab=run|evaluation|about and ?demo=1 (runs the structured example)
    final query = Uri.base.queryParameters;
    _tab = switch (query['tab']) { 'evaluation' => 1, 'about' => 2, _ => 0 };
    _loadConfig().then((_) {
      if (query['demo'] == '1' && _config != null) _controller.runProblem(demoProblem);
    });
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _loadConfig() async {
    setState(() => _loadingConfig = true);
    try {
      final config = await widget.api.config();
      if (mounted) {
        setState(() {
          _config = config;
          _configError = null;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _config = null;
          _configError = e;
        });
      }
    } finally {
      if (mounted) setState(() => _loadingConfig = false);
    }
  }

  static const _destinations = [
    (Icons.play_circle_outline, Icons.play_circle, 'Live run'),
    (Icons.analytics_outlined, Icons.analytics, 'Evaluation'),
    (Icons.account_tree_outlined, Icons.account_tree, 'How it works'),
  ];

  @override
  Widget build(BuildContext context) {
    final pages = [
      RunScreen(controller: _controller, config: _config),
      EvaluationScreen(api: widget.api),
      AboutScreen(config: _config),
    ];
    final body = IndexedStack(index: _tab, children: pages);

    return LayoutBuilder(builder: (context, constraints) {
      final wide = constraints.maxWidth >= 800;
      return Scaffold(
        appBar: AppBar(
          title: const Text('ShiftWise · agent dashboard'),
          actions: [
            Padding(padding: const EdgeInsets.only(right: 12), child: _connectionChip(context)),
          ],
        ),
        body: wide
            ? Row(children: [
                NavigationRail(
                  selectedIndex: _tab,
                  labelType: NavigationRailLabelType.all,
                  onDestinationSelected: (i) => setState(() => _tab = i),
                  destinations: [
                    for (final (icon, selected, label) in _destinations)
                      NavigationRailDestination(icon: Icon(icon), selectedIcon: Icon(selected), label: Text(label)),
                  ],
                ),
                const VerticalDivider(width: 1),
                Expanded(child: body),
              ])
            : body,
        bottomNavigationBar: wide
            ? null
            : NavigationBar(
                selectedIndex: _tab,
                onDestinationSelected: (i) => setState(() => _tab = i),
                destinations: [
                  for (final (icon, selected, label) in _destinations)
                    NavigationDestination(icon: Icon(icon), selectedIcon: Icon(selected), label: label),
                ],
              ),
      );
    });
  }

  Widget _connectionChip(BuildContext context) {
    if (_loadingConfig) {
      return const SizedBox.square(dimension: 18, child: CircularProgressIndicator(strokeWidth: 2));
    }
    final ok = _config != null;
    return Tooltip(
      message: ok ? 'Connected to $apiUrl' : 'Cannot reach $apiUrl: $_configError\nStart it with: uvicorn api:app --reload',
      child: InkWell(
        borderRadius: BorderRadius.circular(999),
        onTap: _loadConfig,
        child: StatusChip(
          ok ? 'API connected · ${_config!.model}' : 'API offline · tap to retry',
          color: ok ? goodColor(context) : badColor(context),
          icon: ok ? Icons.cloud_done_outlined : Icons.cloud_off_outlined,
        ),
      ),
    );
  }
}
