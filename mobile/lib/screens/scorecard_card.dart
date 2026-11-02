import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../widgets.dart';

/// Paneldeki "Demo karnesi": botun kapanmış işlemlerinin R sonucu, öğrenmedeki saklı test
/// beklentisi ve hiç üstünlük yokken (şans) beklenecek aralıkla karşılaştırılır.
class ScorecardCard extends StatelessWidget {
  const ScorecardCard({super.key, required this.card, this.currency = ''});

  final Map<String, dynamic> card;
  final String currency;

  static const _verdicts = {
    'none': ('Bekleniyor', Colors.grey),
    'within': ('Beklenti içinde', profitColor),
    'above': ('Beklentinin üstünde', profitColor),
    'below': ('Beklentinin altında', lossColor),
  };

  @override
  Widget build(BuildContext context) {
    final small = Theme.of(context).textTheme.bodySmall;
    final n = card['trades'] as int;
    final verdict = card['verdict'] as String;
    final (label, color) = _verdicts[verdict] ?? _verdicts['none']!;
    final open = card['open'] as Map<String, dynamic>;
    final since = card['since'] as int?;
    final total = card['total_r'] as num;
    final expected = card['expected_r'] as num;
    final band = (card['band'] as List).cast<num>();
    final luck = (card['luck_band'] as List).cast<num>();
    final needed = card['needed_trades'] as int?;
    final bySymbol = (card['by_symbol'] as Map<String, dynamic>).entries.toList()
      ..sort((a, b) => (b.value['total_r'] as num).compareTo(a.value['total_r'] as num));
    final recent = (card['recent'] as List).cast<Map<String, dynamic>>().take(5);

    return SectionCard(
      title: 'Demo karnesi',
      trailing: Chip(
        avatar: Icon(Icons.circle, size: 12, color: color),
        label: Text(label),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(
          [
            if (since != null) '${dateTime(since).split(' ').first} tarihinden beri',
            '$n kapanmış işlem',
            if ((open['count'] as int) > 0) '${open['count']} açık (şu an ${signed(open['r'] as num)}R)',
          ].join(' • '),
          style: small,
        ),
        const SizedBox(height: 12),
        if (n == 0)
          const Text('İlk işlemler kapanınca karne başlar. Her kapanan işlem, geçmiş testteki '
              'beklentiyle karşılaştırılır.')
        else ...[
          _kv('Sonuç', '${signed(total)}R (${signed(card['profit'] as num)} $currency)', pnlColor(total)),
          _kv('Beklenen', '${signed(expected)}R (aralık ${band[0].toStringAsFixed(1)} … ${band[1].toStringAsFixed(1)})'),
          _kv('Kazanan', '${card['wins']} / $n'),
          _kv('İşlem başı', '${signed(card['avg_r'] as num)}R (beklenen ${signed(card['expected_avg_r'] as num)}R)'),
          const SizedBox(height: 12),
          _RangeBar(value: total.toDouble(), band: band, luck: luck),
          const SizedBox(height: 4),
          Row(children: [
            _legend(profitColor.withValues(alpha: 0.35), 'beklenen aralık', small),
            const SizedBox(width: 12),
            _legend(Colors.grey.withValues(alpha: 0.35), 'şans aralığı', small),
          ]),
          const SizedBox(height: 12),
          Text(_explain(verdict), style: small?.copyWith(color: verdict == 'below' ? lossColor : null)),
        ],
        const SizedBox(height: 6),
        Text(
          card['edge_shown'] == true
              ? 'Sonuç şanstan ayrıştı: hiç üstünlük olmasaydı bu kadar iyi sonuç ihtimali ~%2,5.'
              : needed != null
                  ? 'Üstünlüğü şanstan ayırt etmek için yaklaşık $needed işlem gerekir (şu an $n). '
                      'O zamana kadar karne asıl olarak stratejinin bozulup bozulmadığını gösterir.'
                  : 'Henüz şanstan ayırt edilemiyor.',
          style: small,
        ),
        if (bySymbol.isNotEmpty) ...[
          const SizedBox(height: 12),
          Text('Sembol bazında', style: Theme.of(context).textTheme.titleSmall),
          ...bySymbol.map((e) => _kv(
                '${e.key} • ${e.value['trades']} işlem',
                '${signed(e.value['total_r'] as num)}R (beklenen ${signed(e.value['expected_r'] as num)})',
                pnlColor(e.value['total_r'] as num),
              )),
        ],
        if (recent.isNotEmpty) ...[
          const SizedBox(height: 12),
          Text('Son işlemler', style: Theme.of(context).textTheme.titleSmall),
          ...recent.map((t) => _kv(
                '${dateTime(t['close_time'] as int)} • ${t['symbol']}',
                '${signed(t['r'] as num)}R (${signed(t['profit'] as num)})',
                pnlColor(t['r'] as num),
              )),
        ],
      ]),
    );
  }

  static String _explain(String verdict) => switch (verdict) {
        'within' => 'Sonuç, geçmiş testteki beklentiyle uyumlu.',
        'above' => 'Sonuç beklenenden iyi. Şanslı bir dönem de olabilir; aşırı güvenmeyin.',
        'below' => 'Sonuç, testteki beklentinin %95 aralığının altında: stratejiler canlı piyasada '
            'testteki gibi çalışmıyor olabilir. Gerçek hesaba geçmeyin, birlikte inceleyelim.',
        _ => '',
      };

  static Widget _kv(String k, String v, [Color? color]) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 3),
        child: Row(children: [
          Expanded(child: Text(k)),
          Text(v, style: TextStyle(fontWeight: FontWeight.w600, color: color)),
        ]),
      );

  static Widget _legend(Color color, String text, TextStyle? style) => Row(children: [
        Container(width: 12, height: 12, color: color),
        const SizedBox(width: 4),
        Text(text, style: style),
      ]);
}

/// Yatay ölçek: şans aralığı (gri), beklenen aralık (yeşil), sıfır çizgisi ve gerçek sonuç işareti.
class _RangeBar extends StatelessWidget {
  const _RangeBar({required this.value, required this.band, required this.luck});

  final double value;
  final List<num> band;
  final List<num> luck;

  @override
  Widget build(BuildContext context) {
    final lo = [value, band[0], luck[0]].map((v) => v.toDouble()).reduce(math.min);
    final hi = [value, band[1], luck[1]].map((v) => v.toDouble()).reduce(math.max);
    final pad = (hi - lo) * 0.08 + 0.01;
    final min = lo - pad, span = hi + pad - min;
    final fg = Theme.of(context).colorScheme.onSurface;
    return LayoutBuilder(builder: (context, c) {
      double x(num v) => (v - min) / span * c.maxWidth;
      Widget range(List<num> r, Color color, double top, double h) => Positioned(
            left: x(r[0]), width: x(r[1]) - x(r[0]), top: top, height: h,
            child: Container(decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(3))),
          );
      return SizedBox(
        height: 40,
        child: Stack(children: [
          range(luck, Colors.grey.withValues(alpha: 0.35), 8, 10),
          range(band, profitColor.withValues(alpha: 0.35), 20, 10),
          Positioned(left: x(0) - 0.5, top: 4, width: 1, height: 30, child: Container(color: fg.withValues(alpha: 0.5))),
          Positioned(
            left: x(value) - 2, top: 2, width: 4, height: 32,
            child: Container(color: pnlColor(value)),
          ),
          Positioned(left: x(0) - 6, top: 32, child: Text('0', style: Theme.of(context).textTheme.labelSmall)),
        ]),
      );
    });
  }
}
