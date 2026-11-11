import 'dart:convert';
import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:path_provider/path_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'api.dart';

/// Thrown by screens after an action was safely stored for later instead of sent.
class OfflineQueued implements Exception {}

class QueuedAction {
  final String id, assignmentId, path, key, label;
  final Map? body;                       // JSON actions
  final String? evidenceKind, evidenceFile, evidenceName;   // evidence uploads (bytes live in a private file)
  final DateTime createdAt;
  String? error;
  QueuedAction({required this.id, required this.assignmentId, required this.path, required this.key, required this.label, this.body, this.evidenceKind, this.evidenceFile, this.evidenceName, DateTime? createdAt, this.error})
      : createdAt = createdAt ?? DateTime.now();

  Map toJson() => {'id': id, 'a': assignmentId, 'p': path, 'k': key, 'l': label, 'b': body, 'ek': evidenceKind, 'ef': evidenceFile, 'en': evidenceName, 't': createdAt.toIso8601String(), 'e': error};
  factory QueuedAction.fromJson(Map j) => QueuedAction(id: j['id'], assignmentId: j['a'], path: j['p'], key: j['k'], label: j['l'], body: j['b'], evidenceKind: j['ek'], evidenceFile: j['ef'], evidenceName: j['en'], createdAt: DateTime.parse(j['t']), error: j['e']);
}

/// Store-and-forward for field actions on unreliable networks.
/// - Each action keeps ONE Idempotency-Key for its whole life, so re-sending after a lost reply never repeats it on the server.
/// - Actions are sent strictly in the order they were made (a job's steps depend on each other).
/// - A network failure or server error stops the run and keeps the action; a clear refusal (4xx) moves it to [rejected] so the
///   technician can see what the server did not accept instead of it silently vanishing or blocking everything behind it.
class OfflineQueue extends ChangeNotifier {
  static final OfflineQueue instance = OfflineQueue._();
  OfflineQueue._();
  static const _prefKey = 'offline_queue_v1', _rejKey = 'offline_rejected_v1';
  final List<QueuedAction> pending = [];
  final List<QueuedAction> rejected = [];
  bool _flushing = false;

  bool hasPendingFor(String assignmentId) => pending.any((a) => a.assignmentId == assignmentId);

  Future<void> load() async {
    final p = await SharedPreferences.getInstance();
    pending..clear()..addAll((p.getStringList(_prefKey) ?? []).map((s) => QueuedAction.fromJson(jsonDecode(s))));
    rejected..clear()..addAll((p.getStringList(_rejKey) ?? []).map((s) => QueuedAction.fromJson(jsonDecode(s))));
    notifyListeners();
  }

  Future<void> _save() async {
    final p = await SharedPreferences.getInstance();
    await p.setStringList(_prefKey, pending.map((a) => jsonEncode(a.toJson())).toList());
    await p.setStringList(_rejKey, rejected.map((a) => jsonEncode(a.toJson())).toList());
    notifyListeners();
  }

  static String _id() => Api.newKey();

  Future<void> enqueueJson(String assignmentId, String path, Map body, String key, String label) async {
    pending.add(QueuedAction(id: _id(), assignmentId: assignmentId, path: path, key: key, label: label, body: body));
    await _save();
  }

  Future<void> enqueueEvidence(String assignmentId, String kind, String name, List<int> bytes, String key) async {
    final dir = await getApplicationDocumentsDirectory();
    final id = _id();
    final file = File('${dir.path}/queued_$id.bin');
    await file.writeAsBytes(bytes, flush: true);
    pending.add(QueuedAction(id: id, assignmentId: assignmentId, path: '/technicians/me/assignments/$assignmentId/evidence', key: key, label: 'Photo/document: $name', evidenceKind: kind, evidenceFile: file.path, evidenceName: name));
    await _save();
  }

  Future<void> dismissRejected(String id) async { rejected.removeWhere((a) => a.id == id); await _save(); }

  /// Sends what it can, in order. Safe to call often (app start, resume, timer, after a failed action).
  Future<void> flush() async {
    if (_flushing || pending.isEmpty) return;
    _flushing = true;
    try {
      while (pending.isNotEmpty) {
        final a = pending.first;
        try {
          if (a.evidenceFile != null) {
            final f = File(a.evidenceFile!);
            await Api.instance.uploadEvidence(a.assignmentId, a.evidenceKind!, a.evidenceName!, await f.readAsBytes(), a.key);
            if (await f.exists()) await f.delete();
          } else {
            await Api.instance.postIdem(a.path, a.body ?? {}, a.key);
          }
          pending.removeAt(0);
        } on ApiException catch (e) {
          final retryable = e.status == 0 || e.status == 408 || e.status == 429 || e.status >= 500 || e.status == 401;
          if (retryable) break;   // still offline, server busy, or signed out: keep it and everything behind it
          a.error = e.message;
          pending.removeAt(0);
          rejected.add(a);
          if (a.evidenceFile != null) { final f = File(a.evidenceFile!); if (await f.exists()) await f.delete(); }
        }
        await _save();
      }
    } finally {
      _flushing = false;
      await _save();
    }
  }
}
