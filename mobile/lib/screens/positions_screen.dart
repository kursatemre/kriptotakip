import 'package:flutter/material.dart';

import '../api.dart';
import '../widgets.dart';

class PositionsScreen extends StatefulWidget {
  const PositionsScreen({super.key, required this.api});
  final BotApi api;

  @override
  State<PositionsScreen> createState() => _PositionsScreenState();
}

class _PositionsScreenState extends State<PositionsScreen> {
  List<dynamic>? _open;
  List<dynamic>? _history;
  Object? _error;

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  Future<void> _refresh() async {
    try {
      final results = await Future.wait([widget.api.positions(), widget.api.history()]);
      if (mounted) {
        setState(() {
          _open = results[0];
          _history = results[1];
          _error = null;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  Future<void> _close(Map<String, dynamic> p) async {
    if (!await confirm(context, 'Pozisyonu kapat',
        '${p['symbol']} ${p['side'] == 'buy' ? 'ALIŞ' : 'SATIŞ'} ${p['volume']} lot kapatılsın mı?')) {
      return;
    }
    try {
      await widget.api.closePosition(p['ticket'] as int);
      if (mounted) showInfo(context, '#${p['ticket']} kapatıldı');
      _refresh();
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_open == null) {
      return _error != null
          ? ErrorView(_error!, onRetry: _refresh)
          : const Center(child: CircularProgressIndicator());
    }
    final open = _open!.cast<Map<String, dynamic>>();
    final history = _history!.cast<Map<String, dynamic>>();
    final floating = open.fold<num>(0, (a, p) => a + (p['profit'] as num));
    final realized = history.fold<num>(0, (a, d) => a + (d['profit'] as num));
    final wins = history.where((d) => (d['profit'] as num) > 0).length;

    return DefaultTabController(
      length: 2,
      child: Column(children: [
        TabBar(tabs: [
          Tab(text: 'Açık (${open.length})'),
          Tab(text: 'Geçmiş 30 gün (${history.length})'),
        ]),
        Expanded(
          child: TabBarView(children: [
            RefreshIndicator(
              onRefresh: _refresh,
              child: ListView(children: [
                _summary('Açık kâr/zarar', floating),
                if (open.isEmpty)
                  const Padding(
                    padding: EdgeInsets.all(32),
                    child: Center(child: Text('Açık pozisyon yok')),
                  ),
                ...open.map(_openTile),
              ]),
            ),
            RefreshIndicator(
              onRefresh: _refresh,
              child: ListView(children: [
                _summary(
                    'Gerçekleşen kâr/zarar'
                    '${history.isEmpty ? '' : ' • kazanma %${(wins * 100 / history.length).toStringAsFixed(0)}'}',
                    realized),
                ...history.map(_historyTile),
              ]),
            ),
          ]),
        ),
      ]),
    );
  }

  Widget _summary(String label, num value) => ListTile(
        title: Text(label),
        trailing: Text(signed(value),
            style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: pnlColor(value))),
      );

  Widget _sideBadge(String side) {
    final buy = side == 'buy';
    return CircleAvatar(
      backgroundColor: (buy ? profitColor : lossColor).withValues(alpha: 0.2),
      child: Icon(buy ? Icons.arrow_upward : Icons.arrow_downward,
          color: buy ? profitColor : lossColor),
    );
  }

  Widget _openTile(Map<String, dynamic> p) {
    final profit = p['profit'] as num;
    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
      child: ListTile(
        leading: _sideBadge(p['side']),
        title: Text('${p['symbol']} • ${p['volume']} lot'),
        subtitle: Text('Giriş ${p['open_price']}\nSL ${p['sl']} • TP ${p['tp']}'),
        isThreeLine: true,
        trailing: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            Text(signed(profit),
                style: TextStyle(fontWeight: FontWeight.bold, color: pnlColor(profit))),
            InkWell(
              onTap: () => _close(p),
              child: const Padding(
                padding: EdgeInsets.only(top: 6),
                child: Text('KAPAT', style: TextStyle(color: lossColor, fontSize: 12)),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _historyTile(Map<String, dynamic> d) {
    final profit = d['profit'] as num;
    return ListTile(
      leading: _sideBadge(d['side']),
      title: Text('${d['symbol']} • ${d['volume']} lot'),
      subtitle: Text('${dateTime(d['time'])} • çıkış ${d['price']}'),
      trailing: Text(signed(profit),
          style: TextStyle(fontWeight: FontWeight.bold, color: pnlColor(profit))),
    );
  }
}
