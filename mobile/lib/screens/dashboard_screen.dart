import 'dart:async';

import 'package:flutter/material.dart';

import '../api.dart';
import '../widgets.dart';

class DashboardScreen extends StatefulWidget {
  const DashboardScreen({super.key, required this.api});
  final BotApi api;

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  Map<String, dynamic>? _status;
  Object? _error;
  bool _busy = false;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _refresh();
    _timer = Timer.periodic(const Duration(seconds: 5), (_) => _refresh());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _refresh() async {
    try {
      final s = await widget.api.status();
      if (mounted) {
        setState(() {
          _status = s;
          _error = null;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  Future<void> _toggle(bool running) async {
    if (running &&
        !await confirm(context, 'Botu başlat',
            'Bot, stratejinin sinyallerine göre otomatik işlem açacak. Devam edilsin mi?')) {
      return;
    }
    setState(() => _busy = true);
    try {
      final s = running ? await widget.api.start() : await widget.api.stop();
      if (mounted) setState(() => _status = s);
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _closeAll() async {
    if (!await confirm(context, 'Tümünü kapat', 'Botun açtığı TÜM pozisyonlar kapatılacak.')) return;
    try {
      final r = await widget.api.closeAll();
      if (mounted) showInfo(context, '${r['closed']} pozisyon kapatıldı');
      _refresh();
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = _status;
    if (s == null) {
      return _error != null
          ? ErrorView(_error!, onRetry: _refresh)
          : const Center(child: CircularProgressIndicator());
    }
    final acc = s['account'] as Map<String, dynamic>;
    final trading = s['trading'] as Map<String, dynamic>;
    final running = s['running'] as bool;
    final cur = acc['currency'] as String;
    final balance = acc['balance'] as num;
    final equity = acc['equity'] as num;
    final dayStart = s['day_start_equity'] as num;
    final signals = (s['last_signals'] as Map<String, dynamic>);

    return RefreshIndicator(
      onRefresh: _refresh,
      child: ListView(padding: const EdgeInsets.symmetric(vertical: 8), children: [
        if (_error != null) _banner(Icons.cloud_off, 'Bağlantı sorunu: $_error', lossColor),
        if (acc['is_demo'] != true)
          _banner(Icons.warning_amber, 'DİKKAT: GERÇEK HESAP', lossColor),
        if ((s['halted_reason'] as String).isNotEmpty)
          _banner(Icons.pause_circle, s['halted_reason'], Colors.orange),
        if ((s['last_error'] as String).isNotEmpty)
          _banner(Icons.error_outline, s['last_error'], lossColor),
        SectionCard(
          title: 'Bot',
          trailing: Chip(
            avatar: Icon(Icons.circle, size: 12, color: running ? profitColor : Colors.grey),
            label: Text(running ? 'ÇALIŞIYOR' : 'DURDU'),
          ),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('${s['strategy_title']}', style: Theme.of(context).textTheme.titleSmall),
            const SizedBox(height: 4),
            Text('${(trading['symbols'] as List).join(', ')} • ${trading['timeframe']}'),
            if ((s['last_check'] as int) > 0)
              Text('Son kontrol: ${dateTime(s['last_check'])}',
                  style: Theme.of(context).textTheme.bodySmall),
            const SizedBox(height: 16),
            SizedBox(
              width: double.infinity,
              child: FilledButton.icon(
                style: FilledButton.styleFrom(
                  backgroundColor: running ? lossColor : profitColor,
                  foregroundColor: Colors.white,
                  padding: const EdgeInsets.symmetric(vertical: 14),
                ),
                onPressed: _busy ? null : () => _toggle(!running),
                icon: Icon(running ? Icons.stop : Icons.play_arrow),
                label: Text(running ? 'Botu durdur' : 'Botu başlat'),
              ),
            ),
            const SizedBox(height: 8),
            SizedBox(
              width: double.infinity,
              child: OutlinedButton.icon(
                onPressed: _closeAll,
                icon: const Icon(Icons.close),
                label: const Text('Tüm pozisyonları kapat'),
              ),
            ),
          ]),
        ),
        SectionCard(
          title: 'Hesap',
          trailing: Chip(label: Text(acc['is_demo'] == true ? 'DEMO' : 'GERÇEK')),
          child: Column(children: [
            _kv('Sunucu', '${acc['server']} • ${acc['login']}'),
            _kv('Bakiye', money(balance, cur)),
            _kv('Varlık (equity)', money(equity, cur)),
            _kv('Açık kâr/zarar', signed(equity - balance), pnlColor(equity - balance)),
            if (dayStart > 0)
              _kv('Bugün', signed(equity - dayStart), pnlColor(equity - dayStart)),
            _kv('Serbest teminat', money(acc['margin_free'] as num, cur)),
          ]),
        ),
        if (signals.isNotEmpty)
          SectionCard(
            title: 'Son sinyaller',
            child: Column(
              children: signals.entries.map((e) {
                final sig = e.value['signal'] as int;
                final label = sig > 0 ? 'AL' : (sig < 0 ? 'SAT' : 'Yok');
                return _kv('${e.key} • ${dateTime(e.value['time'])}', label,
                    sig > 0 ? profitColor : (sig < 0 ? lossColor : null));
              }).toList(),
            ),
          ),
      ]),
    );
  }

  Widget _kv(String k, String v, [Color? color]) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Row(children: [
          Expanded(child: Text(k)),
          Text(v, style: TextStyle(fontWeight: FontWeight.w600, color: color)),
        ]),
      );

  Widget _banner(IconData icon, String text, Color color) => Card(
        margin: const EdgeInsets.fromLTRB(16, 8, 16, 0),
        color: color.withValues(alpha: 0.18),
        child: ListTile(leading: Icon(icon, color: color), title: Text(text)),
      );
}
