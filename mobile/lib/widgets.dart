import 'package:flutter/material.dart';

const profitColor = Color(0xFF2EBD85);
const lossColor = Color(0xFFF6465D);

Color pnlColor(num v) => v > 0 ? profitColor : (v < 0 ? lossColor : Colors.grey);

/// Strateji parametrelerinin Türkçe adları
const paramLabels = {
  'fast': 'Hızlı EMA',
  'slow': 'Yavaş EMA',
  'trend': 'Trend EMA',
  'period': 'Periyot',
  'oversold': 'Aşırı satım',
  'overbought': 'Aşırı alım',
  'mult': 'Std. sapma çarpanı',
};

String paramLabel(String key) => paramLabels[key] ?? key;

String money(num v, [String currency = '']) {
  final s = v.toStringAsFixed(2);
  return currency.isEmpty ? s : '$s $currency';
}

String signed(num v) => '${v > 0 ? '+' : ''}${v.toStringAsFixed(2)}';

String dateTime(int unix) {
  final d = DateTime.fromMillisecondsSinceEpoch(unix * 1000);
  String two(int n) => n.toString().padLeft(2, '0');
  return '${two(d.day)}.${two(d.month)}.${d.year} ${two(d.hour)}:${two(d.minute)}';
}

void showError(BuildContext context, Object e) {
  ScaffoldMessenger.of(context).showSnackBar(
    SnackBar(content: Text(e.toString()), backgroundColor: lossColor),
  );
}

void showInfo(BuildContext context, String msg) {
  ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
}

Future<bool> confirm(BuildContext context, String title, String message) async {
  final ok = await showDialog<bool>(
    context: context,
    builder: (c) => AlertDialog(
      title: Text(title),
      content: Text(message),
      actions: [
        TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Vazgeç')),
        FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Evet')),
      ],
    ),
  );
  return ok ?? false;
}

class ErrorView extends StatelessWidget {
  const ErrorView(this.error, {super.key, required this.onRetry});
  final Object error;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          const Icon(Icons.cloud_off, size: 48, color: lossColor),
          const SizedBox(height: 12),
          Text(error.toString(), textAlign: TextAlign.center),
          const SizedBox(height: 12),
          OutlinedButton.icon(
            onPressed: onRetry,
            icon: const Icon(Icons.refresh),
            label: const Text('Tekrar dene'),
          ),
        ]),
      ),
    );
  }
}

/// Backtest sonucu: işlem sayısı, kazanma oranı, PF, getiri, düşüş.
class MetricsRow extends StatelessWidget {
  const MetricsRow(this.m, {super.key});
  final Map<String, dynamic> m;

  @override
  Widget build(BuildContext context) {
    final pf = m['profit_factor'];
    Widget cell(String label, String value, [Color? color]) => Expanded(
          child: Column(children: [
            Text(label, style: Theme.of(context).textTheme.labelSmall),
            const SizedBox(height: 2),
            Text(value,
                style: TextStyle(fontWeight: FontWeight.w600, color: color)),
          ]),
        );
    final ret = (m['net_return_pct'] as num);
    return Row(children: [
      cell('İşlem', '${m['trades']}'),
      cell('Kazanç', '%${m['win_rate_pct']}'),
      cell('PF', pf == null ? '∞' : '$pf'),
      cell('Getiri', '%${signed(ret)}', pnlColor(ret)),
      cell('Max düşüş', '%${m['max_drawdown_pct']}', lossColor),
    ]);
  }
}

class SectionCard extends StatelessWidget {
  const SectionCard({super.key, required this.title, required this.child, this.trailing});
  final String title;
  final Widget child;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.fromLTRB(16, 8, 16, 8),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(child: Text(title, style: Theme.of(context).textTheme.titleMedium)),
            ?trailing,
          ]),
          const SizedBox(height: 12),
          child,
        ]),
      ),
    );
  }
}
