import 'package:flutter/material.dart';

import '../widgets.dart';

const _strategyNames = {
  'ema_trend': 'EMA kesişimi',
  'rsi_pullback': 'RSI geri çekilme',
  'donchian_breakout': 'Donchian kırılım',
  'bollinger_reversion': 'Bollinger dönüş',
  'rsi2_reversion': 'RSI(2) dönüş',
  'tsmom': 'Momentum',
  'ml_boost': 'Makine öğrenmesi',
};

/// Paneldeki "Öğrenen bot" kartı: modu açıp kapatma, öğrenmeyi başlatma ve botun her sembol
/// için seçtiği stratejiyi saklı test sonuçlarıyla gösterme.
class LearningCard extends StatefulWidget {
  const LearningCard({
    super.key,
    required this.learning,
    required this.busy,
    required this.onToggle,
    required this.onLearn,
  });

  final Map<String, dynamic> learning;
  final bool busy;
  final ValueChanged<bool> onToggle;
  final VoidCallback onLearn;

  @override
  State<LearningCard> createState() => _LearningCardState();
}

class _LearningCardState extends State<LearningCard> {
  bool _showAll = false;

  @override
  Widget build(BuildContext context) {
    final l = widget.learning;
    final enabled = l['enabled'] == true;
    final running = l['running'] == true;
    final summary = l['summary'] as Map<String, dynamic>?;
    final assignments = (l['assignments'] as Map<String, dynamic>? ?? {}).entries.toList()
      ..sort((a, b) {
        final aa = a.value['active'] == true, ba = b.value['active'] == true;
        if (aa != ba) return aa ? -1 : 1;
        return ((b.value['holdout']['avg_r'] as num)).compareTo(a.value['holdout']['avg_r'] as num);
      });
    final active = assignments.where((e) => e.value['active'] == true).length;
    final shown = _showAll ? assignments : assignments.take(8).toList();
    final small = Theme.of(context).textTheme.bodySmall;

    return SectionCard(
      title: 'Öğrenen bot',
      trailing: Switch(value: enabled, onChanged: widget.busy ? null : widget.onToggle),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(
          enabled
              ? 'Bot her sembol için stratejiyi kendisi seçiyor ve sadece saklı testi geçen '
                  'sembollerde işlem açıyor.'
              : 'Açınca bot tüm sembolleri araştırır, her sembole en iyi stratejiyi atar ve sadece '
                  'görülmemiş veride de kârlı kalan sembollerde işlem yapar.',
          style: small,
        ),
        const SizedBox(height: 12),
        if (running) ...[
          const LinearProgressIndicator(),
          const SizedBox(height: 6),
          Text('${l['progress'] ?? 'Öğreniyor...'}', style: small),
          const SizedBox(height: 12),
        ],
        if (l['time'] != null) ...[
          Text('Son öğrenme: ${dateTime(l['time'] as int)} • ${l['timeframe']} • '
              '${l['symbols_researched']} sembol araştırıldı'),
          if (summary != null)
            Text(
              '$active sembol işlem için uygun • seçilenlerin saklı test ortalaması '
              '${signed(summary['holdout_avg_r'] as num)}R/işlem',
              style: small,
            ),
          const SizedBox(height: 8),
        ] else if (!running)
          const Padding(
            padding: EdgeInsets.only(bottom: 8),
            child: Text('Henüz öğrenme yapılmadı.'),
          ),
        SizedBox(
          width: double.infinity,
          child: OutlinedButton.icon(
            onPressed: running || widget.busy ? null : widget.onLearn,
            icon: const Icon(Icons.psychology_outlined),
            label: Text(running ? 'Öğreniyor...' : 'Şimdi öğren'),
          ),
        ),
        if (assignments.isNotEmpty) ...[
          const SizedBox(height: 12),
          ...shown.map((e) => _row(e.key, e.value as Map<String, dynamic>)),
          if (assignments.length > 8)
            TextButton(
              onPressed: () => setState(() => _showAll = !_showAll),
              child: Text(_showAll ? 'Daha az göster' : 'Tümünü göster (${assignments.length})'),
            ),
        ],
      ]),
    );
  }

  Widget _row(String symbol, Map<String, dynamic> a) {
    final h = a['holdout'] as Map<String, dynamic>;
    final isActive = a['active'] == true;
    final avg = h['avg_r'] as num;
    final pf = h['pf'];
    return ListTile(
      contentPadding: EdgeInsets.zero,
      dense: true,
      leading: Icon(isActive ? Icons.check_circle : Icons.remove_circle_outline,
          color: isActive ? profitColor : Colors.grey),
      title: Text('$symbol • ${_strategyNames[a['strategy']] ?? a['strategy']}'),
      subtitle: Text('Saklı test: ${h['trades']} işlem, PF ${pf ?? '∞'}, '
          'kazanma %${h['win_rate']}'),
      trailing: Text('${avg >= 0 ? '+' : ''}${avg.toStringAsFixed(2)}R',
          style: TextStyle(fontWeight: FontWeight.bold, color: pnlColor(avg))),
    );
  }
}
