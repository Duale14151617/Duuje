import 'package:flutter_test/flutter_test.dart';
import 'package:duale_technician/offline_queue.dart';

void main() {
  test('a queued action survives serialisation with its idempotency key', () {
    final a = QueuedAction(id: '1', assignmentId: 'a1', path: '/x', key: 'KEY', label: 'Status: Arrived', body: {'status': 'Arrived'});
    final b = QueuedAction.fromJson(a.toJson());
    expect(b.key, 'KEY');
    expect(b.body, {'status': 'Arrived'});
    expect(b.assignmentId, 'a1');
  });
}
