import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api.dart';
import 'screens/backtest_screen.dart';
import 'screens/connect_screen.dart';
import 'screens/dashboard_screen.dart';
import 'screens/events_screen.dart';
import 'screens/positions_screen.dart';
import 'screens/strategy_screen.dart';

void main() => runApp(const GcmBotApp());

class GcmBotApp extends StatefulWidget {
  const GcmBotApp({super.key});

  @override
  State<GcmBotApp> createState() => _GcmBotAppState();
}

class _GcmBotAppState extends State<GcmBotApp> {
  BotApi? _api;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final prefs = await SharedPreferences.getInstance();
    final url = prefs.getString('url');
    final token = prefs.getString('token');
    setState(() {
      _api = (url != null && token != null) ? BotApi(url, token) : null;
      _loading = false;
    });
  }

  Future<void> _connect(String url, String token) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('url', url);
    await prefs.setString('token', token);
    setState(() => _api = BotApi(url, token));
  }

  Future<void> _disconnect() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('token');
    setState(() => _api = null);
  }

  @override
  Widget build(BuildContext context) {
    final scheme = ColorScheme.fromSeed(
      seedColor: const Color(0xFF1E6FFF),
      brightness: Brightness.dark,
    );
    return MaterialApp(
      title: 'GCM Bot',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(colorScheme: scheme, useMaterial3: true),
      home: _loading
          ? const Scaffold(body: Center(child: CircularProgressIndicator()))
          : _api == null
              ? ConnectScreen(
                  onConnect: _connect,
                  // Web sürümü botun kendisinden servis ediliyorsa adres aynıdır
                  defaultUrl: kIsWeb ? Uri.base.origin : '',
                )
              : HomeScreen(api: _api!, onDisconnect: _disconnect),
    );
  }
}

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key, required this.api, required this.onDisconnect});
  final BotApi api;
  final VoidCallback onDisconnect;

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  int _index = 0;

  static const _titles = ['Panel', 'Pozisyonlar', 'Strateji', 'Backtest', 'Kayıtlar'];

  @override
  Widget build(BuildContext context) {
    final api = widget.api;
    final pages = [
      DashboardScreen(api: api),
      PositionsScreen(api: api),
      StrategyScreen(api: api),
      BacktestScreen(api: api, onApplied: () => setState(() => _index = 2)),
      EventsScreen(api: api),
    ];
    return Scaffold(
      appBar: AppBar(
        title: Text(_titles[_index]),
        actions: [
          IconButton(
            tooltip: 'Bağlantıyı kes',
            icon: const Icon(Icons.logout),
            onPressed: widget.onDisconnect,
          ),
        ],
      ),
      // Ekranlar arasında geçince her sayfa yeniden yüklenir (güncel veri için)
      body: KeyedSubtree(key: ValueKey(_index), child: pages[_index]),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _index,
        onDestinationSelected: (i) => setState(() => _index = i),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.dashboard_outlined), label: 'Panel'),
          NavigationDestination(icon: Icon(Icons.swap_vert), label: 'Pozisyon'),
          NavigationDestination(icon: Icon(Icons.tune), label: 'Strateji'),
          NavigationDestination(icon: Icon(Icons.science_outlined), label: 'Backtest'),
          NavigationDestination(icon: Icon(Icons.list_alt), label: 'Kayıtlar'),
        ],
      ),
    );
  }
}
