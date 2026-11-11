import 'package:flutter/material.dart';
import '../api.dart';
import 'auth.dart';

class ProfileScreen extends StatefulWidget {
  final VoidCallback onSignOut;
  const ProfileScreen({super.key, required this.onSignOut});
  @override
  State<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen> {
  Map? me, profile;
  List trades = [], areas = [], myAreas = [], rels = [];
  Set<String> pickedSkills = {}, pickedAreas = {};
  String? error;

  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    try {
      final api = Api.instance;
      final r = await Future.wait<dynamic>([
        api.get<Map>('/me'), api.get<Map>('/technicians/me'), api.get<List>('/catalog/trades'),
        api.get<List>('/catalog/service-areas'), api.get<List>('/technicians/me/service-areas'), api.get<List>('/technicians/me/relationships'),
      ]);
      setState(() {
        me = r[0]; profile = r[1]; trades = r[2]; areas = r[3]; myAreas = r[4]; rels = r[5];
        pickedSkills = {for (final s in profile!['skills']) s['id'] as String};
        pickedAreas = {for (final a in myAreas) a['id'] as String};
      });
    } on ApiException catch (e) {
      setState(() => error = e.message);
    }
  }

  Future<void> guard(Future<void> Function() f, String ok) async {
    try { await f(); if (mounted) snack(context, ok); await load(); } on ApiException catch (e) { if (mounted) snack(context, e.message); }
  }

  @override
  Widget build(BuildContext context) {
    if (error != null) return Center(child: Text(error!));
    if (profile == null) return const Center(child: CircularProgressIndicator());
    final status = {for (final s in profile!['skills']) s['id'] as String: s};
    return ListView(padding: const EdgeInsets.all(12), children: [
      ListTile(title: Text(profile!['displayName'], style: Theme.of(context).textTheme.titleLarge), subtitle: Text('${me!['email']}')),
      const Divider(),
      Text('Skills', style: Theme.of(context).textTheme.titleMedium),
      const Text('Claim the skills you have. A reviewer verifies each one before you can be matched to jobs.'),
      for (final t in trades) ...[
        if ((t['skills'] as List).isNotEmpty) Padding(padding: const EdgeInsets.only(top: 8), child: Text(t['name'], style: const TextStyle(fontWeight: FontWeight.bold))),
        for (final s in t['skills'])
          CheckboxListTile(
            dense: true,
            value: pickedSkills.contains(s['id']),
            title: Text(s['name']),
            subtitle: status[s['id']] == null ? null : Text(status[s['id']]['verification'] + (status[s['id']]['expiresOn'] != null ? ' · expires ${status[s['id']]['expiresOn']}' : '')),
            onChanged: (v) => setState(() => v! ? pickedSkills.add(s['id']) : pickedSkills.remove(s['id'])),
          ),
      ],
      FilledButton(onPressed: () => guard(() => Api.instance.put('/technicians/me/skills', {'skillIds': pickedSkills.toList()}), 'Skills saved.'), child: const Text('Save skills')),
      const Divider(height: 32),
      Text('Service areas', style: Theme.of(context).textTheme.titleMedium),
      if (areas.isEmpty) const Text('No service areas have been set up yet.'),
      for (final a in areas)
        CheckboxListTile(dense: true, value: pickedAreas.contains(a['id']), title: Text(a['name']), onChanged: (v) => setState(() => v! ? pickedAreas.add(a['id']) : pickedAreas.remove(a['id']))),
      if (areas.isNotEmpty) FilledButton(onPressed: () => guard(() => Api.instance.put('/technicians/me/service-areas', {'serviceAreaIds': pickedAreas.toList()}), 'Service areas saved.'), child: const Text('Save service areas')),
      const Divider(height: 32),
      Text('Companies', style: Theme.of(context).textTheme.titleMedium),
      if (rels.isEmpty) const Text('No company relationships yet.'),
      for (final r in rels)
        ListTile(
          title: Text(r['company']),
          subtitle: Text('${r['type']} · ${r['status']}'),
          trailing: r['status'] == 'Invited'
              ? Row(mainAxisSize: MainAxisSize.min, children: [
                  IconButton(icon: const Icon(Icons.check), tooltip: 'Accept', onPressed: () => guard(() => Api.instance.post('/technicians/me/relationships/${r['id']}/respond', {'accept': true}), 'Accepted.')),
                  IconButton(icon: const Icon(Icons.close), tooltip: 'Decline', onPressed: () => guard(() => Api.instance.post('/technicians/me/relationships/${r['id']}/respond', {'accept': false}), 'Declined.')),
                ])
              : null,
        ),
      const Divider(height: 32),
      ListTile(
        leading: const Icon(Icons.security),
        title: const Text('Two-factor authentication'),
        subtitle: Text(me!['mfaEnabled'] == true ? 'On' : 'Off'),
        onTap: me!['mfaEnabled'] == true ? null : () async { await Navigator.push(context, MaterialPageRoute(builder: (_) => const MfaSetupScreen())); load(); },
      ),
      OutlinedButton(onPressed: widget.onSignOut, child: const Text('Sign out on all devices')),
    ]);
  }
}

class MfaSetupScreen extends StatefulWidget {
  const MfaSetupScreen({super.key});
  @override
  State<MfaSetupScreen> createState() => _MfaSetupScreenState();
}

class _MfaSetupScreenState extends State<MfaSetupScreen> {
  String? secret;
  List? codes;
  final code = TextEditingController();

  @override
  void initState() {
    super.initState();
    Api.instance.post<Map>('/auth/mfa/setup').then((r) => setState(() => secret = r['secret'])).catchError((e) { if (mounted) snack(context, '$e'); });
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Two-factor authentication')),
        body: ListView(padding: const EdgeInsets.all(20), children: [
          if (codes != null) ...[
            const Text('Save these recovery codes now. They are shown once and each works one time.', style: TextStyle(fontWeight: FontWeight.bold)),
            const SizedBox(height: 8),
            SelectableText(codes!.join('\n'), style: const TextStyle(fontFamily: 'monospace', fontSize: 18)),
            const SizedBox(height: 16),
            FilledButton(onPressed: () => Navigator.pop(context), child: const Text('I saved them')),
          ] else if (secret == null) const Center(child: CircularProgressIndicator())
          else ...[
            const Text('In your authenticator app, add an account using this setup key, then enter the 6-digit code it shows.'),
            const SizedBox(height: 8),
            SelectableText(secret!, style: const TextStyle(fontFamily: 'monospace', fontSize: 18)),
            TextField(controller: code, keyboardType: TextInputType.number, maxLength: 6, decoration: const InputDecoration(labelText: 'Code')),
            FilledButton(onPressed: () async {
              try {
                final r = await Api.instance.post<Map>('/auth/mfa/enable', {'code': code.text.trim()});
                setState(() => codes = r['recoveryCodes']);
              } on ApiException catch (e) { if (mounted) snack(context, e.message); }
            }, child: const Text('Turn on')),
          ],
        ]),
      );
}
