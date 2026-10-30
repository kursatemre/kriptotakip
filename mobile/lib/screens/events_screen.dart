import 'package:flutter/material.dart';

import '../api.dart';
import '../widgets.dart';

class EventsScreen extends StatefulWidget {
  const EventsScreen({super.key, required this.api});
  final BotApi api;

  @override
  State<EventsScreen> createState() => _EventsScreenState();
}

class _EventsScreenState extends State<EventsScreen> {
  List<dynamic>? _events;
  Object? _error;

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  Future<void> _refresh() async {
    try {
      final e = await widget.api.events();
      if (mounted) {
        setState(() {
          _events = e;
          _error = null;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_events == null) {
      return _error != null
          ? ErrorView(_error!, onRetry: _refresh)
          : const Center(child: CircularProgressIndicator());
    }
    final events = _events!.cast<Map<String, dynamic>>();
    return RefreshIndicator(
      onRefresh: _refresh,
      child: events.isEmpty
          ? ListView(children: const [
              Padding(padding: EdgeInsets.all(32), child: Center(child: Text('Kayıt yok'))),
            ])
          : ListView.separated(
              itemCount: events.length,
              separatorBuilder: (_, _) => const Divider(height: 1),
              itemBuilder: (_, i) {
                final e = events[i];
                final (icon, color) = switch (e['level']) {
                  'error' => (Icons.error_outline, lossColor),
                  'warn' => (Icons.warning_amber, Colors.orange),
                  _ => (Icons.info_outline, Colors.blueGrey),
                };
                return ListTile(
                  leading: Icon(icon, color: color),
                  title: Text(e['message']),
                  subtitle: Text(dateTime(e['time'])),
                );
              },
            ),
    );
  }
}
