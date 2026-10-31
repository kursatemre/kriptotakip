import 'package:flutter/material.dart';

import '../api.dart';
import '../widgets.dart';

/// Strateji, semboller, zaman dilimi ve risk ayarları.
class StrategyScreen extends StatefulWidget {
  const StrategyScreen({super.key, required this.api});
  final BotApi api;

  @override
  State<StrategyScreen> createState() => _StrategyScreenState();
}

const _riskFields = {
  'risk_per_trade_pct': 'İşlem başı risk (% sermaye)',
  'sl_atr_mult': 'Stop-loss (x ATR)',
  'tp_atr_mult': 'Take-profit (x ATR)',
  'max_open_positions': 'Maks. açık pozisyon',
  'max_daily_loss_pct': 'Günlük maks. zarar (%)',
  'max_drawdown_pct': 'Zirveden maks. düşüş (%, 0 = kapalı)',
  'max_consecutive_losses': 'Üst üste zararda sembolü durdur (adet, 0 = kapalı)',
  'loss_pause_hours': 'Sembol bekleme süresi (saat)',
};

class _StrategyScreenState extends State<StrategyScreen> {
  List<Map<String, dynamic>> _strategies = [];
  List<String> _timeframes = [];
  Object? _error;
  bool _loaded = false;
  bool _saving = false;

  String _strategy = '';
  String _timeframe = 'H1';
  bool _closeOnOpposite = true;
  final _symbols = TextEditingController();
  final Map<String, TextEditingController> _params = {};
  final Map<String, TextEditingController> _risk = {
    for (final k in _riskFields.keys) k: TextEditingController(),
  };

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final res = await Future.wait([widget.api.strategies(), widget.api.status()]);
      final meta = res[0];
      final status = res[1];
      final trading = status['trading'] as Map<String, dynamic>;
      final risk = status['risk'] as Map<String, dynamic>;
      if (!mounted) return;
      setState(() {
        _strategies = (meta['strategies'] as List).cast<Map<String, dynamic>>();
        _timeframes = (meta['timeframes'] as List).cast<String>();
        _strategy = trading['strategy'];
        _timeframe = trading['timeframe'];
        _closeOnOpposite = trading['close_on_opposite'];
        _symbols.text = (trading['symbols'] as List).join(', ');
        _setParams(trading['params'] as Map<String, dynamic>);
        for (final k in _riskFields.keys) {
          _risk[k]!.text = '${risk[k]}';
        }
        _loaded = true;
        _error = null;
      });
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  Map<String, dynamic> get _meta =>
      _strategies.firstWhere((s) => s['name'] == _strategy, orElse: () => _strategies.first);

  void _setParams(Map<String, dynamic> values) {
    _params.clear();
    final defaults = _meta['default_params'] as Map<String, dynamic>;
    for (final k in defaults.keys) {
      _params[k] = TextEditingController(text: '${values[k] ?? defaults[k]}');
    }
  }

  num? _num(String s) => num.tryParse(s.trim().replaceAll(',', '.'));

  Future<void> _save() async {
    final params = <String, dynamic>{};
    for (final e in _params.entries) {
      final v = _num(e.value.text);
      if (v == null) return showError(context, '${paramLabel(e.key)} sayı olmalı');
      params[e.key] = v;
    }
    final risk = <String, dynamic>{};
    for (final e in _risk.entries) {
      final v = _num(e.value.text);
      if (v == null) return showError(context, '${_riskFields[e.key]} sayı olmalı');
      risk[e.key] = v;
    }
    setState(() => _saving = true);
    try {
      await widget.api.saveSettings(
        trading: {
          'strategy': _strategy,
          'params': params,
          'symbols': _symbols.text.split(RegExp(r'[,\s]+')).where((s) => s.isNotEmpty).toList(),
          'timeframe': _timeframe,
          'close_on_opposite': _closeOnOpposite,
        },
        risk: risk,
      );
      if (mounted) showInfo(context, 'Ayarlar kaydedildi');
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (!_loaded) {
      return _error != null
          ? ErrorView(_error!, onRetry: _load)
          : const Center(child: CircularProgressIndicator());
    }
    return ListView(padding: const EdgeInsets.only(bottom: 24), children: [
      SectionCard(
        title: 'Strateji',
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          DropdownButtonFormField<String>(
            key: ValueKey(_strategy),
            initialValue: _strategy,
            isExpanded: true,
            decoration: const InputDecoration(border: OutlineInputBorder()),
            items: _strategies
                .map((s) => DropdownMenuItem<String>(value: s['name'], child: Text(s['title'])))
                .toList(),
            onChanged: (v) => setState(() {
              _strategy = v!;
              _setParams({}); // yeni stratejinin varsayılanları
            }),
          ),
          const SizedBox(height: 8),
          Text(_meta['description'], style: Theme.of(context).textTheme.bodySmall),
          const SizedBox(height: 12),
          Wrap(
            spacing: 12,
            runSpacing: 12,
            children: _params.entries
                .map((e) => SizedBox(width: 140, child: _numberField(e.value, paramLabel(e.key))))
                .toList(),
          ),
        ]),
      ),
      SectionCard(
        title: 'Piyasa',
        child: Column(children: [
          TextField(
            controller: _symbols,
            autocorrect: false,
            textCapitalization: TextCapitalization.characters,
            decoration: const InputDecoration(
              labelText: 'Semboller (virgülle)',
              helperText: 'MT5 Piyasa Gözlemi\'ndeki adlarla aynı olmalı',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 12),
          DropdownButtonFormField<String>(
            key: ValueKey('tf$_timeframe'),
            initialValue: _timeframe,
            decoration: const InputDecoration(labelText: 'Zaman dilimi', border: OutlineInputBorder()),
            items: _timeframes.map((t) => DropdownMenuItem(value: t, child: Text(t))).toList(),
            onChanged: (v) => setState(() => _timeframe = v!),
          ),
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('Ters sinyalde pozisyonu kapat'),
            value: _closeOnOpposite,
            onChanged: (v) => setState(() => _closeOnOpposite = v),
          ),
        ]),
      ),
      SectionCard(
        title: 'Risk yönetimi',
        child: Column(
          children: _riskFields.entries
              .map((e) => Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: _numberField(_risk[e.key]!, e.value),
                  ))
              .toList(),
        ),
      ),
      Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16),
        child: FilledButton.icon(
          onPressed: _saving ? null : _save,
          icon: const Icon(Icons.save),
          label: const Text('Kaydet'),
        ),
      ),
    ]);
  }

  Widget _numberField(TextEditingController c, String label) => TextField(
        controller: c,
        keyboardType: const TextInputType.numberWithOptions(decimal: true),
        decoration: InputDecoration(labelText: label, border: const OutlineInputBorder()),
      );
}
