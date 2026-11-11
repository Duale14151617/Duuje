import 'package:flutter/material.dart';
import '../api.dart';
import 'auth.dart';

/// The technician's own payments. Company-paid jobs show what the company has confirmed; for jobs the customer pays
/// directly, the technician records what they actually received (kept as self-reported until the company reconciles it).
class EarningsScreen extends StatefulWidget {
  const EarningsScreen({super.key});
  @override
  State<EarningsScreen> createState() => _EarningsScreenState();
}

class _EarningsScreenState extends State<EarningsScreen> {
  late Future<List> f = Api.instance.get<List>('/technicians/me/payables');
  void reload() => setState(() => f = Api.instance.get<List>('/technicians/me/payables'));

  Future<String?> ask(String title, {String? initial}) async {
    final c = TextEditingController(text: initial);
    return showDialog<String>(
      context: context,
      builder: (_) => AlertDialog(
        title: Text(title),
        content: TextField(controller: c, keyboardType: TextInputType.text),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(context, c.text.trim()), child: const Text('OK')),
        ],
      ),
    );
  }

  // One key per tap: if the connection drops and the technician taps again with the same key, nothing is recorded twice.
  final Map<String, String> _keys = {};

  Future<void> acknowledge(Map p) async {
    final text = await ask('Amount you received (${p['currency']})', initial: '${p['outstanding']}');
    final amount = double.tryParse(text ?? '');
    if (amount == null || amount <= 0) return;
    final key = _keys.putIfAbsent('${p['id']}:$amount', Api.newKey);
    try {
      await Api.instance.postIdem('/technicians/me/payables/${p['id']}/acknowledge', {'amount': amount, 'method': 'cash'}, key);
      _keys.remove('${p['id']}:$amount');
      if (mounted) snack(context, 'Recorded. The company will reconcile it.');
      reload();
    } on ApiException catch (e) { if (mounted) snack(context, e.message); }
  }

  Future<void> dispute(Map p) async {
    final text = await ask('What is wrong with this payment?');
    if (text == null || text.isEmpty) return;
    try {
      await Api.instance.post('/technicians/me/payables/${p['id']}/dispute', {'description': text});
      if (mounted) snack(context, 'Dispute sent to the company.');
    } on ApiException catch (e) { if (mounted) snack(context, e.message); }
  }

  @override
  Widget build(BuildContext context) => FutureBuilder<List>(
        future: f,
        builder: (c, s) {
          if (s.hasError) return Center(child: Text('${s.error}'));
          if (!s.hasData) return const Center(child: CircularProgressIndicator());
          if (s.data!.isEmpty) return const Center(child: Text('No payments yet. They appear after your work is approved.'));
          return RefreshIndicator(
            onRefresh: () async => reload(),
            child: ListView(children: [
              for (final p in s.data!)
                Card(
                  margin: const EdgeInsets.all(8),
                  child: Padding(
                    padding: const EdgeInsets.all(12),
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text('${p['jobReference']} · ${p['company']}', style: const TextStyle(fontWeight: FontWeight.bold)),
                      Text('${p['amount']} ${p['currency']} — ${p['payerType'] == 'customer' ? 'paid by the customer directly' : 'paid by the company'}'),
                      Text('Status: ${p['settlement']} · received ${p['paid']} · remaining ${p['outstanding']}'),
                      for (final pay in (p['payments'] as List))
                        Text('  ${pay['amount']} via ${pay['method']} (${pay['verified'] == true ? 'verified' : 'self-reported'}${pay['reconciled'] == true ? ', reconciled' : ''})', style: const TextStyle(fontSize: 12)),
                      Row(children: [
                        if (p['payerType'] == 'customer' && (p['outstanding'] as num) > 0)
                          TextButton(onPressed: () => acknowledge(p), child: const Text('I received money')),
                        TextButton(onPressed: () => dispute(p), child: const Text('Report a problem')),
                      ]),
                    ]),
                  ),
                ),
            ]),
          );
        },
      );
}
