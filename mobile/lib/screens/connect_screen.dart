import 'package:flutter/material.dart';

import '../api.dart';
import '../widgets.dart';

class ConnectScreen extends StatefulWidget {
  const ConnectScreen({super.key, required this.onConnect, this.defaultUrl = ''});
  final Future<void> Function(String url, String token) onConnect;
  final String defaultUrl;

  @override
  State<ConnectScreen> createState() => _ConnectScreenState();
}

class _ConnectScreenState extends State<ConnectScreen> {
  late final _url = TextEditingController(
      text: widget.defaultUrl.isEmpty ? 'http://192.168.1.10:8000' : widget.defaultUrl);
  final _token = TextEditingController();
  bool _busy = false;

  Future<void> _submit() async {
    setState(() => _busy = true);
    try {
      final api = BotApi(_url.text, _token.text.trim());
      final s = await api.status();
      if (!mounted) return;
      final acc = s['account'] as Map<String, dynamic>;
      showInfo(context, 'Bağlandı: ${acc['server']} (${acc['is_demo'] ? 'DEMO' : 'GERÇEK'})');
      await widget.onConnect(api.baseUrl, api.token);
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                const Icon(Icons.smart_toy_outlined, size: 64),
                const SizedBox(height: 12),
                Text('GCM Bot',
                    textAlign: TextAlign.center,
                    style: Theme.of(context).textTheme.headlineMedium),
                const SizedBox(height: 8),
                const Text(
                  'Bilgisayarınızda çalışan botun adresini ve token\'ını girin. '
                  'Bu bilgiler bot başlarken konsolda yazar.',
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: 24),
                TextField(
                  controller: _url,
                  keyboardType: TextInputType.url,
                  autocorrect: false,
                  decoration: const InputDecoration(
                    labelText: 'Sunucu adresi',
                    border: OutlineInputBorder(),
                  ),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _token,
                  autocorrect: false,
                  obscureText: true,
                  decoration: const InputDecoration(
                    labelText: 'Token',
                    border: OutlineInputBorder(),
                  ),
                  onSubmitted: (_) => _submit(),
                ),
                const SizedBox(height: 20),
                FilledButton.icon(
                  onPressed: _busy ? null : _submit,
                  icon: _busy
                      ? const SizedBox(
                          width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                      : const Icon(Icons.link),
                  label: const Text('Bağlan'),
                ),
              ]),
            ),
          ),
        ),
      ),
    );
  }
}
