import 'package:flutter/material.dart';

import '../api.dart';
import '../widgets.dart';

/// Stratejileri botun bağlı olduğu MT5 hesabının geçmiş verisinde dener.
class BacktestScreen extends StatefulWidget {
  const BacktestScreen({super.key, required this.api, required this.onApplied});
  final BotApi api;
  final VoidCallback onApplied;

  @override
  State<BacktestScreen> createState() => _BacktestScreenState();
}

class _BacktestScreenState extends State<BacktestScreen> {
  List<Map<String, dynamic>> _strategies = [];
  List<String> _timeframes = [];
  final _symbol = TextEditingController();
  final _bars = TextEditingController(text: '5000');
  String _timeframe = 'H1';
  String _strategy = '';
  String _mode = 'compare';
  bool _running = false;
  Object? _error;
  Map<String, dynamic>? _result;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final res = await Future.wait([widget.api.strategies(), widget.api.status()]);
      final trading = res[1]['trading'] as Map<String, dynamic>;
      if (!mounted) return;
      setState(() {
        _strategies = (res[0]['strategies'] as List).cast<Map<String, dynamic>>();
        _timeframes = (res[0]['timeframes'] as List).cast<String>();
        _symbol.text = (trading['symbols'] as List).first;
        _timeframe = trading['timeframe'];
        _strategy = trading['strategy'];
        _error = null;
      });
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  String _title(String name) =>
      _strategies.firstWhere((s) => s['name'] == name, orElse: () => {'title': name})['title'];

  Future<void> _run() async {
    setState(() {
      _running = true;
      _result = null;
    });
    try {
      final r = await widget.api.backtest({
        'symbol': _symbol.text.trim(),
        'timeframe': _timeframe,
        'bars': int.tryParse(_bars.text) ?? 5000,
        'mode': _mode,
        'strategy': _strategy,
      });
      if (mounted) setState(() => _result = r);
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => _running = false);
    }
  }

  Future<void> _apply(String strategy, Map<String, dynamic> params) async {
    if (!await confirm(context, 'Stratejiyi kullan',
        '${_title(strategy)} $params botun stratejisi olarak ayarlansın mı?')) {
      return;
    }
    try {
      await widget.api.saveSettings(trading: {
        'strategy': strategy,
        'params': params,
        'timeframe': _timeframe,
      });
      if (!mounted) return;
      showInfo(context, 'Strateji güncellendi');
      widget.onApplied();
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_strategies.isEmpty) {
      return _error != null
          ? ErrorView(_error!, onRetry: _load)
          : const Center(child: CircularProgressIndicator());
    }
    return ListView(padding: const EdgeInsets.only(bottom: 24), children: [
      SectionCard(
        title: 'Test ayarları',
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          SegmentedButton<String>(
            showSelectedIcon: false,
            segments: const [
              ButtonSegment(value: 'compare', label: Text('Karşılaştır')),
              ButtonSegment(value: 'single', label: Text('Tek')),
              ButtonSegment(value: 'optimize', label: Text('Optimize')),
            ],
            selected: {_mode},
            onSelectionChanged: (v) => setState(() {
              _mode = v.first;
              _result = null;
            }),
          ),
          const SizedBox(height: 8),
          Text(
            switch (_mode) {
              'compare' => 'Tüm stratejileri varsayılan ayarlarla dener ve sıralar.',
              'single' => 'Seçilen stratejiyi mevcut ayarlarıyla dener.',
              _ => 'Verinin ilk %70\'inde en iyi parametreleri arar, son %30\'unda (görülmemiş veri) doğrular.',
            },
            style: Theme.of(context).textTheme.bodySmall,
          ),
          const SizedBox(height: 12),
          if (_mode != 'compare') ...[
            DropdownButtonFormField<String>(
              key: ValueKey(_strategy),
              initialValue: _strategy,
              isExpanded: true,
              decoration: const InputDecoration(labelText: 'Strateji', border: OutlineInputBorder()),
              items: _strategies
                  .map((s) => DropdownMenuItem<String>(value: s['name'], child: Text(s['title'])))
                  .toList(),
              onChanged: (v) => setState(() => _strategy = v!),
            ),
            const SizedBox(height: 12),
          ],
          Row(children: [
            Expanded(
              child: TextField(
                controller: _symbol,
                textCapitalization: TextCapitalization.characters,
                decoration: const InputDecoration(labelText: 'Sembol', border: OutlineInputBorder()),
              ),
            ),
            const SizedBox(width: 8),
            SizedBox(
              width: 90,
              child: DropdownButtonFormField<String>(
                key: ValueKey('tf$_timeframe'),
                initialValue: _timeframe,
                decoration: const InputDecoration(labelText: 'Zaman', border: OutlineInputBorder()),
                items: _timeframes.map((t) => DropdownMenuItem(value: t, child: Text(t))).toList(),
                onChanged: (v) => setState(() => _timeframe = v!),
              ),
            ),
            const SizedBox(width: 8),
            SizedBox(
              width: 90,
              child: TextField(
                controller: _bars,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(labelText: 'Bar', border: OutlineInputBorder()),
              ),
            ),
          ]),
          const SizedBox(height: 16),
          FilledButton.icon(
            onPressed: _running ? null : _run,
            icon: _running
                ? const SizedBox(
                    width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                : const Icon(Icons.play_arrow),
            label: Text(_running ? 'Test ediliyor...' : 'Testi çalıştır'),
          ),
        ]),
      ),
      if (_result != null) ..._results(_result!),
      if (_result != null)
        const Padding(
          padding: EdgeInsets.all(16),
          child: Text(
            'Geçmiş performans gelecekteki sonuçları garanti etmez. '
            'PF = kâr faktörü (1\'in üstü kârlı). Seçtiğiniz stratejiyi önce demoda izleyin.',
            style: TextStyle(color: Colors.grey, fontSize: 12),
          ),
        ),
    ]);
  }

  List<Widget> _results(Map<String, dynamic> r) {
    switch (r['mode']) {
      case 'compare':
        return (r['results'] as List).cast<Map<String, dynamic>>().asMap().entries.map((e) {
          final row = e.value;
          return SectionCard(
            title: '${e.key + 1}. ${_title(row['strategy'])}',
            trailing: TextButton(
              onPressed: () => _apply(row['strategy'], row['params']),
              child: const Text('Kullan'),
            ),
            child: MetricsRow(row['metrics']),
          );
        }).toList();
      case 'optimize':
        return [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
            child: Text(
              'Eğitim: ${r['train_bars']} bar • Test: ${r['test_bars']} bar. '
              'Test sonucu eğitime yakın olan parametreler daha güvenilirdir.',
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ),
          ...(r['results'] as List).cast<Map<String, dynamic>>().map((row) => SectionCard(
                title: (row['params'] as Map<String, dynamic>)
                    .entries
                    .map((e) => '${paramLabel(e.key)}: ${e.value}')
                    .join(' • '),
                trailing: TextButton(
                  onPressed: () => _apply(r['strategy'], row['params']),
                  child: const Text('Kullan'),
                ),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  const Text('Eğitim', style: TextStyle(color: Colors.grey)),
                  MetricsRow(row['train']),
                  const Divider(height: 20),
                  const Text('Test (görülmemiş veri)', style: TextStyle(color: Colors.grey)),
                  MetricsRow(row['test']),
                ]),
              )),
        ];
      default:
        final m = r['metrics'] as Map<String, dynamic>;
        final trades = (r['trades'] as List).cast<Map<String, dynamic>>().reversed;
        return [
          SectionCard(
            title: '${_title(_strategy)} • son ${trades.length} işlem',
            child: Column(children: [
              MetricsRow(m),
              const Divider(height: 24),
              ...trades.map((t) {
                final rr = t['r'] as num;
                return ListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  title: Text('${t['side'] == 'buy' ? 'ALIŞ' : 'SATIŞ'} • ${dateTime(t['entry_time'])}'),
                  subtitle: Text('${t['entry']} → ${t['exit']} (${t['reason']})'),
                  trailing: Text('${signed(rr)}R',
                      style: TextStyle(color: pnlColor(rr), fontWeight: FontWeight.bold)),
                );
              }),
            ]),
          ),
        ];
    }
  }
}
