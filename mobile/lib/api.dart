import 'dart:convert';

import 'package:http/http.dart' as http;

class ApiException implements Exception {
  ApiException(this.message);
  final String message;

  @override
  String toString() => message;
}

/// Bilgisayarda çalışan botun REST API istemcisi.
class BotApi {
  BotApi(String baseUrl, this.token)
      : baseUrl = baseUrl.trim().replaceAll(RegExp(r'/+$'), '');

  final String baseUrl;
  final String token;

  Future<dynamic> _request(
    String method,
    String path, {
    Object? body,
    Duration timeout = const Duration(seconds: 15),
  }) async {
    final uri = Uri.parse('$baseUrl$path');
    final headers = {
      'Authorization': 'Bearer $token',
      'Content-Type': 'application/json',
    };
    final http.Response res;
    final client = http.Client();
    try {
      final req = http.Request(method, uri)..headers.addAll(headers);
      if (body != null) req.body = jsonEncode(body);
      final streamed = await client.send(req).timeout(timeout);
      res = await http.Response.fromStream(streamed).timeout(timeout);
    } catch (e) {
      throw ApiException('Sunucuya ulaşılamadı ($baseUrl). Bot bilgisayarda açık mı? ($e)');
    } finally {
      client.close();
    }
    final text = utf8.decode(res.bodyBytes);
    final data = text.isEmpty ? null : jsonDecode(text);
    if (res.statusCode == 401) throw ApiException('Token hatalı.');
    if (res.statusCode >= 400) {
      final detail = data is Map ? data['detail'] : null;
      throw ApiException(detail?.toString() ?? 'Hata (${res.statusCode})');
    }
    return data;
  }

  Future<Map<String, dynamic>> status() async => await _request('GET', '/api/status');
  Future<Map<String, dynamic>> start() async => await _request('POST', '/api/bot/start');
  Future<Map<String, dynamic>> stop() async => await _request('POST', '/api/bot/stop');
  Future<List<dynamic>> positions() async => await _request('GET', '/api/positions');
  Future<void> closePosition(int ticket) => _request('POST', '/api/positions/$ticket/close');
  Future<Map<String, dynamic>> closeAll() async => await _request('POST', '/api/positions/close-all');
  Future<List<dynamic>> history({int days = 30}) async =>
      await _request('GET', '/api/history?days=$days');
  Future<List<dynamic>> events() async => await _request('GET', '/api/events');
  Future<Map<String, dynamic>> strategies() async => await _request('GET', '/api/strategies');
  Future<Map<String, dynamic>> crypto() async => await _request('GET', '/api/crypto');

  Future<Map<String, dynamic>> saveSettings({
    Map<String, dynamic>? trading,
    Map<String, dynamic>? risk,
  }) async =>
      await _request('PUT', '/api/settings', body: {
        'trading': ?trading,
        'risk': ?risk,
      });

  Future<Map<String, dynamic>> backtest(Map<String, dynamic> body) async =>
      await _request('POST', '/api/backtest',
          body: body, timeout: const Duration(minutes: 3));
}
