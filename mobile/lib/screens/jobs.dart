import 'package:flutter/material.dart';
import '../api.dart';
import 'auth.dart';
import 'job_detail.dart';

/// Offers and assigned jobs. The company decides assignments; the technician only accepts or declines.
class JobsScreen extends StatefulWidget {
  const JobsScreen({super.key});
  @override
  State<JobsScreen> createState() => _JobsScreenState();
}

class _JobsScreenState extends State<JobsScreen> {
  late Future<List> f = load();
  Future<List> load() => Api.instance.get<List>('/technicians/me/assignments');
  void refresh() => setState(() => f = load());

  Future<void> respond(String id, bool accept) async {
    String? reason;
    if (!accept) {
      final c = TextEditingController();
      reason = await showDialog<String>(
        context: context,
        builder: (_) => AlertDialog(
          title: const Text('Decline this job?'),
          content: TextField(controller: c, decoration: const InputDecoration(labelText: 'Reason (optional)')),
          actions: [TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')), FilledButton(onPressed: () => Navigator.pop(context, c.text), child: const Text('Decline'))],
        ),
      );
      if (reason == null) return;
    }
    try {
      await Api.instance.post('/technicians/me/assignments/$id/respond', {'accept': accept, 'reason': reason});
      refresh();
    } on ApiException catch (e) {
      if (mounted) snack(context, e.message);
    }
  }

  @override
  Widget build(BuildContext context) => RefreshIndicator(
        onRefresh: () async { refresh(); await f; },
        child: FutureBuilder<List>(
          future: f,
          builder: (c, s) {
            if (s.hasError) return ListView(children: [Padding(padding: const EdgeInsets.all(24), child: Text('${s.error}'))]);
            if (!s.hasData) return const Center(child: CircularProgressIndicator());
            if (s.data!.isEmpty) return ListView(children: const [Padding(padding: EdgeInsets.all(24), child: Text('No jobs yet. Companies you work with will offer jobs here.'))]);
            return ListView(padding: const EdgeInsets.all(12), children: [
              for (final a in s.data!)
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(14),
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Row(children: [Expanded(child: Text('${a['job']['reference']} · ${a['job']['trade']}', style: const TextStyle(fontWeight: FontWeight.bold))), Chip(label: Text(a['status']))]),
                      Text('${a['company']} · ${a['job']['priority']} priority'),
                      Text('${when(a['job']['scheduledStart'])} to ${when(a['job']['scheduledEnd'])}'),
                      const SizedBox(height: 6),
                      Text(a['job']['description'] ?? ''),
                      if (a['status'] == 'Accepted')
                        Padding(
                          padding: const EdgeInsets.only(top: 10),
                          child: FilledButton(
                            onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => JobDetailScreen(assignmentId: a['assignmentId']))).then((_) => refresh()),
                            child: const Text('Open job'),
                          ),
                        ),
                      if (a['status'] == 'Offered')
                        Padding(
                          padding: const EdgeInsets.only(top: 10),
                          child: Row(children: [
                            FilledButton(onPressed: () => respond(a['assignmentId'], true), child: const Text('Accept')),
                            const SizedBox(width: 8),
                            OutlinedButton(onPressed: () => respond(a['assignmentId'], false), child: const Text('Decline')),
                          ]),
                        ),
                    ]),
                  ),
                ),
            ]);
          },
        ),
      );
}

class AvailabilityScreen extends StatefulWidget {
  const AvailabilityScreen({super.key});
  @override
  State<AvailabilityScreen> createState() => _AvailabilityScreenState();
}

class _AvailabilityScreenState extends State<AvailabilityScreen> {
  late Future<List> f = Api.instance.get<List>('/technicians/me/availability');
  void refresh() => setState(() => f = Api.instance.get<List>('/technicians/me/availability'));

  Future<DateTime?> pick(String help, DateTime initial) async {
    final d = await showDatePicker(context: context, initialDate: initial, firstDate: DateTime.now(), lastDate: DateTime.now().add(const Duration(days: 365)), helpText: help);
    if (d == null || !mounted) return null;
    final t = await showTimePicker(context: context, initialTime: TimeOfDay.fromDateTime(initial));
    if (t == null) return null;
    return DateTime(d.year, d.month, d.day, t.hour, t.minute);
  }

  Future<void> add() async {
    final start = await pick('Available from', DateTime.now().add(const Duration(hours: 1)));
    if (start == null) return;
    final end = await pick('Available until', start.add(const Duration(hours: 8)));
    if (end == null) return;
    try {
      await Api.instance.post('/technicians/me/availability', {'startsAt': start.toUtc().toIso8601String(), 'endsAt': end.toUtc().toIso8601String()});
      refresh();
    } on ApiException catch (e) {
      if (mounted) snack(context, e.message);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        floatingActionButton: FloatingActionButton.extended(onPressed: add, icon: const Icon(Icons.add), label: const Text('Add window')),
        body: FutureBuilder<List>(
          future: f,
          builder: (c, s) {
            if (s.hasError) return Center(child: Text('${s.error}'));
            if (!s.hasData) return const Center(child: CircularProgressIndicator());
            if (s.data!.isEmpty) return const Center(child: Padding(padding: EdgeInsets.all(24), child: Text('Add the times you can work. Companies only see you for jobs inside these windows.')));
            return ListView(children: [
              for (final w in s.data!)
                ListTile(
                  title: Text('${when(w['startsAt'])} to ${when(w['endsAt'])}'),
                  trailing: IconButton(icon: const Icon(Icons.delete_outline), tooltip: 'Remove', onPressed: () async {
                    try { await Api.instance.delete('/technicians/me/availability/${w['id']}'); refresh(); } on ApiException catch (e) { if (mounted) snack(context, e.message); }
                  }),
                ),
            ]);
          },
        ),
      );
}
