import 'dart:async';

import 'package:flutter/material.dart';

import '../api.dart';
import '../widgets.dart';

/// Kripto fiyatları (eski KriptoTakip uygulaması). Fiyatlar bot üzerinden CoinGecko'dan gelir;
/// bot sonucu 60 sn önbellekte tuttuğu için sık yenilemek CoinGecko sınırına takılmaz.
class CryptoScreen extends StatefulWidget {
  const CryptoScreen({super.key, required this.api});
  final BotApi api;

  @override
  State<CryptoScreen> createState() => _CryptoScreenState();
}

const _coinNames = {
  'bitcoin': 'Bitcoin (BTC)',
  'ethereum': 'Ethereum (ETH)',
  'cardano': 'Cardano (ADA)',
  'solana': 'Solana (SOL)',
  'ripple': 'XRP',
  'binancecoin': 'BNB',
  'dogecoin': 'Dogecoin (DOGE)',
  'tether': 'Tether (USDT)',
};

const _currencySymbols = {'usd': r'$', 'eur': '€', 'try': '₺', 'gbp': '£'};

String _coinName(String id) =>
    _coinNames[id] ?? (id.isEmpty ? id : '${id[0].toUpperCase()}${id.substring(1)}');

/// Fiyatı büyüklüğüne göre yeterli ondalıkla ve binlik ayırıcıyla yazar
/// (ADA gibi 1$ altı coinlerde 2 ondalık değişimi göstermez).
String _price(num v, String currency) {
  final digits = v >= 1 ? 2 : (v >= 0.01 ? 4 : 8);
  final parts = v.toStringAsFixed(digits).split('.');
  final whole = parts[0].replaceAllMapped(RegExp(r'\B(?=(\d{3})+(?!\d))'), (_) => ',');
  final s = '$whole.${parts[1]}';
  final symbol = _currencySymbols[currency];
  return symbol != null ? '$symbol$s' : '$s ${currency.toUpperCase()}';
}

class _CryptoScreenState extends State<CryptoScreen> {
  Map<String, dynamic>? _data;
  Object? _error;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _refresh();
    _timer = Timer.periodic(const Duration(seconds: 30), (_) => _refresh());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _refresh() async {
    try {
      final d = await widget.api.crypto();
      if (mounted) {
        setState(() {
          _data = d;
          _error = null;
        });
      }
    } catch (e) {
      // Veri varken hata olursa eski fiyatlar ekranda kalır, üstte uyarı gösterilir
      if (mounted) setState(() => _error = e);
    }
  }

  @override
  Widget build(BuildContext context) {
    final d = _data;
    if (d == null) {
      return _error != null
          ? ErrorView(_error!, onRetry: _refresh)
          : const Center(child: CircularProgressIndicator());
    }
    final currency = d['currency'] as String;
    final coins = (d['coins'] as List).cast<Map<String, dynamic>>();
    final warning = _error != null
        ? 'Güncellenemedi: $_error'
        : (d['stale'] == true ? 'CoinGecko\'ya ulaşılamadı, son bilinen fiyatlar gösteriliyor' : null);
    return RefreshIndicator(
      onRefresh: _refresh,
      child: ListView(padding: const EdgeInsets.only(bottom: 24), children: [
        ListTile(
          dense: true,
          title: Text('Son güncelleme: ${dateTime(d['updated'] as int)}'),
          subtitle: warning == null ? null : Text(warning, style: const TextStyle(color: Colors.orange)),
          trailing: const Text('24 saat'),
        ),
        ...coins.map((c) => _coinCard(c, currency)),
      ]),
    );
  }

  Widget _coinCard(Map<String, dynamic> c, String currency) {
    final price = c['price'] as num?;
    final change = c['change_24h_pct'] as num?;
    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
      child: ListTile(
        title: Text(_coinName(c['id'] as String)),
        subtitle: Text(
          price == null ? 'Veri yok (coin adı doğru mu?)' : _price(price, currency),
          style: Theme.of(context).textTheme.titleLarge,
        ),
        trailing: change == null
            ? null
            : Row(mainAxisSize: MainAxisSize.min, children: [
                if (change != 0)
                  Icon(change > 0 ? Icons.arrow_upward : Icons.arrow_downward,
                      color: pnlColor(change), size: 20),
                Text('%${signed(change)}',
                    style: TextStyle(fontWeight: FontWeight.bold, color: pnlColor(change))),
              ]),
      ),
    );
  }
}
