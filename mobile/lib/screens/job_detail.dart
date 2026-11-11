import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import '../api.dart';
import '../offline_queue.dart';
import 'auth.dart';

/// Field workflow for one accepted job: status steps, evidence, scope changes and the work report.
/// Customer details appear here only because this technician accepted the job.
class JobDetailScreen extends StatefulWidget {
  final String assignmentId;
  const JobDetailScreen({super.key, required this.assignmentId});
  @override
  State<JobDetailScreen> createState() => _JobDetailScreenState();
}

class _JobDetailScreenState extends State<JobDetailScreen> {
  late Future<Map> f = load();
  Future<Map> load() => Api.instance.get<Map>('/technicians/me/assignments/${widget.assignmentId}/job');
  void refresh() => setState(() => f = load());
  bool busy = false;
  final summary = TextEditingController();
  final hours = TextEditingController();
  final scope = TextEditingController();
  String kind = 'progress';

  static const next = {
    'Accepted': ('EnRoute', "I'm on my way"),
    'EnRoute': ('Arrived', "I've arrived"),
    'Arrived': ('InProgress', 'Start work'),
    'ReturnedForCorrection': ('InProgress', 'Resume work'),
  };

  Future<void> guard(Future<void> Function() fn, [String? ok]) async {
    setState(() => busy = true);
    try {
      await fn();
      if (ok != null && mounted) snack(context, ok);
      refresh();
    } on OfflineQueued {
      if (mounted) snack(context, 'No connection. Saved on this phone; it will be sent automatically, in order.');
    } on ApiException catch (e) {
      if (mounted) snack(context, e.message);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  // One key per user action. If the connection drops, the SAME key is kept with the queued copy, so a request that
  // actually reached the server is replayed from its stored result instead of being applied twice.
  Future<void> sendOrQueue(String path, Map body, String label) async {
    final key = Api.newKey();
    try {
      await Api.instance.postIdem(path, body, key);
    } on ApiException catch (e) {
      if (e.status != 0) rethrow;
      await OfflineQueue.instance.enqueueJson(widget.assignmentId, path, body, key, label);
      throw OfflineQueued();
    }
  }

  Future<void> setStatus(String to) => guard(() => sendOrQueue('/technicians/me/assignments/${widget.assignmentId}/status',
      {'status': to, 'clientTime': DateTime.now().toUtc().toIso8601String()}, 'Status: $to'));   // device time is kept: the action may reach the server much later

  Future<void> addEvidence() async {
    final r = await FilePicker.platform.pickFiles(type: FileType.custom, allowedExtensions: ['pdf', 'jpg', 'jpeg', 'png'], withData: true);
    final file = r?.files.single;
    if (file == null || file.bytes == null) return;
    if (file.size > 5000000) { if (mounted) snack(context, 'File is larger than 5 MB.'); return; }
    await guard(() async {
      final key = Api.newKey();
      try {
        await Api.instance.uploadEvidence(widget.assignmentId, kind, file.name, file.bytes!, key);
      } on ApiException catch (e) {
        if (e.status != 0) rethrow;
        await OfflineQueue.instance.enqueueEvidence(widget.assignmentId, kind, file.name, file.bytes!, key);
        throw OfflineQueued();
      }
    }, 'Evidence uploaded.');
  }

  Future<void> reportScope() async {
    if (scope.text.trim().isEmpty) return;
    await guard(() async {
      final text = scope.text.trim();
      scope.clear();
      await sendOrQueue('/technicians/me/assignments/${widget.assignmentId}/scope-change', {'description': text}, 'Scope change');
    }, 'Sent to the supervisor.');
  }

  Future<void> submit() async {
    if (summary.text.trim().isEmpty) { snack(context, 'Describe the work you did.'); return; }
    await guard(() async {
      final body = {'summary': summary.text.trim(), if (hours.text.trim().isNotEmpty) 'hoursWorked': double.tryParse(hours.text.trim())};
      summary.clear();
      await sendOrQueue('/technicians/me/assignments/${widget.assignmentId}/report', body, 'Work report');
    }, 'Submitted for review.');
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Job')),
        body: FutureBuilder<Map>(
          future: f,
          builder: (c, s) {
            if (s.hasError) return Center(child: Padding(padding: const EdgeInsets.all(24), child: Text('${s.error}')));
            if (!s.hasData) return const Center(child: CircularProgressIndicator());
            final d = s.data!;
            final job = d['job'] as Map;
            final status = job['status'] as String;
            final cust = d['customer'] as Map?;
            final step = next[status];
            return ListView(padding: const EdgeInsets.all(14), children: [
              Text('${job['reference']} · ${job['trade']}', style: Theme.of(context).textTheme.titleLarge),
              Row(children: [Chip(label: Text(status)), const SizedBox(width: 8), Text('${d['company']}')]),
              Text('${when(job['scheduledStart'])} to ${when(job['scheduledEnd'])}'),
              const SizedBox(height: 6),
              Text(job['description'] ?? ''),
              if (d['returnNote'] != null) Card(color: Colors.orange.shade50, child: Padding(padding: const EdgeInsets.all(12), child: Text('Returned for correction: ${d['returnNote']}'))),
              if (cust != null)
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(12),
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      const Text('Customer', style: TextStyle(fontWeight: FontWeight.bold)),
                      Text('${cust['name']} · ${cust['phone']}'),
                      Text('${cust['location']}: ${cust['address']}'),
                      if (cust['accessInstructions'] != null) Text('Access: ${cust['accessInstructions']}'),
                    ]),
                  ),
                ),
              if (step != null)
                Padding(padding: const EdgeInsets.symmetric(vertical: 10), child: FilledButton(onPressed: busy ? null : () => setStatus(step.$1), child: Text(step.$2))),
              if (status == 'InProgress' || status == 'Arrived' || status == 'ReturnedForCorrection') ...[
                const Divider(),
                Text('Evidence (${d['evidenceCount']})', style: Theme.of(context).textTheme.titleMedium),
                Row(children: [
                  DropdownButton<String>(value: kind, items: const [for (final k in ['before', 'progress', 'after', 'other']) DropdownMenuItem(value: k, child: Text(k))], onChanged: (v) => setState(() => kind = v!)),
                  const SizedBox(width: 12),
                  OutlinedButton.icon(onPressed: busy ? null : addEvidence, icon: const Icon(Icons.add_a_photo_outlined), label: const Text('Add photo or PDF')),
                ]),
                TextField(controller: scope, decoration: const InputDecoration(labelText: 'Scope change (optional)'), maxLines: 2),
                Align(alignment: Alignment.centerLeft, child: TextButton(onPressed: busy ? null : reportScope, child: const Text('Report scope change'))),
              ],
              if (status == 'InProgress' || status == 'ReturnedForCorrection') ...[
                const Divider(),
                Text('Work report', style: Theme.of(context).textTheme.titleMedium),
                TextField(controller: summary, decoration: const InputDecoration(labelText: 'What did you do?'), maxLines: 4),
                TextField(controller: hours, decoration: const InputDecoration(labelText: 'Hours worked (optional)'), keyboardType: const TextInputType.numberWithOptions(decimal: true)),
                const SizedBox(height: 8),
                FilledButton(onPressed: busy ? null : submit, child: const Text('Submit for review')),
              ],
              if (status == 'AwaitingReview') const Padding(padding: EdgeInsets.all(12), child: Text('Submitted. Your supervisor is reviewing the work.')),
              if (status == 'Completed') const Padding(padding: EdgeInsets.all(12), child: Text('This job is approved. Thank you.')),
            ]);
          },
        ),
      );
}
