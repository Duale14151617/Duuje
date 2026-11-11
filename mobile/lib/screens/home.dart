import 'package:flutter/material.dart';
import '../api.dart';
import 'auth.dart';
import 'documents.dart';
import 'dart:async';
import 'earnings.dart';
import '../offline_queue.dart';
import 'jobs.dart';
import 'profile.dart';

class Home extends StatefulWidget {
  final VoidCallback onSignOut;
  const Home({super.key, required this.onSignOut});
  @override
  State<Home> createState() => _HomeState();
}

class _HomeState extends State<Home> with WidgetsBindingObserver {
  int tab = 0;
  bool? hasProfile;
  Timer? timer;

  @override
  void initState() {
    super.initState();
    check();
    WidgetsBinding.instance.addObserver(this);
    OfflineQueue.instance.load().then((_) => OfflineQueue.instance.flush());
    timer = Timer.periodic(const Duration(seconds: 30), (_) => OfflineQueue.instance.flush());   // retries while the app is open
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) OfflineQueue.instance.flush();
  }

  @override
  void dispose() {
    timer?.cancel();
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  Future<void> check() async {
    try {
      await Api.instance.get<Map>('/technicians/me');
      setState(() => hasProfile = true);
    } on ApiException catch (e) {
      if (e.status == 404) setState(() => hasProfile = false);
      else if (mounted) snack(context, e.message);
    }
  }

  void showRejected(BuildContext context) => showDialog(
        context: context,
        builder: (_) => AlertDialog(
          title: const Text('Not accepted'),
          content: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            for (final a in OfflineQueue.instance.rejected) Padding(padding: const EdgeInsets.only(bottom: 8), child: Text('${a.label}: ${a.error ?? 'refused'}')),
          ]),
          actions: [TextButton(onPressed: () { for (final a in List.of(OfflineQueue.instance.rejected)) { OfflineQueue.instance.dismissRejected(a.id); } Navigator.pop(context); }, child: const Text('Dismiss'))],
        ),
      );

  Future<void> signOut() async {
    try { await Api.instance.post('/auth/logout-all'); } catch (_) {}
    await Api.instance.setToken(null);
    widget.onSignOut();
  }

  @override
  Widget build(BuildContext context) {
    if (hasProfile == null) return const Scaffold(body: Center(child: CircularProgressIndicator()));
    if (hasProfile == false) return CreateProfile(onCreated: () => setState(() => hasProfile = true), onSignOut: signOut);
    final pages = [const JobsScreen(), const AvailabilityScreen(), const DocumentsScreen(), const EarningsScreen(), ProfileScreen(onSignOut: signOut)];
    return Scaffold(
      appBar: AppBar(title: const Text('Duale BuildLink'), actions: [
        IconButton(icon: const Icon(Icons.notifications_outlined), tooltip: 'Notifications', onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const NotificationsScreen()))),
      ]),
      body: Column(children: [
        ListenableBuilder(listenable: OfflineQueue.instance, builder: (c, _) {
          final q = OfflineQueue.instance;
          if (q.pending.isEmpty && q.rejected.isEmpty) return const SizedBox.shrink();
          return MaterialBanner(
            content: Text([
              if (q.pending.isNotEmpty) '${q.pending.length} update(s) waiting to be sent',
              if (q.rejected.isNotEmpty) '${q.rejected.length} not accepted by the server',
            ].join(' · ')),
            actions: [
              if (q.pending.isNotEmpty) TextButton(onPressed: q.flush, child: const Text('Send now')),
              if (q.rejected.isNotEmpty) TextButton(onPressed: () => showRejected(context), child: const Text('Details')),
            ],
          );
        }),
        Expanded(child: pages[tab]),
      ]),
      bottomNavigationBar: NavigationBar(
        selectedIndex: tab,
        onDestinationSelected: (i) => setState(() => tab = i),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.work_outline), label: 'Jobs'),
          NavigationDestination(icon: Icon(Icons.event_available_outlined), label: 'Availability'),
          NavigationDestination(icon: Icon(Icons.folder_outlined), label: 'Documents'),
          NavigationDestination(icon: Icon(Icons.payments_outlined), label: 'Earnings'),
          NavigationDestination(icon: Icon(Icons.person_outline), label: 'Profile'),
        ],
      ),
    );
  }
}

class CreateProfile extends StatefulWidget {
  final VoidCallback onCreated, onSignOut;
  const CreateProfile({super.key, required this.onCreated, required this.onSignOut});
  @override
  State<CreateProfile> createState() => _CreateProfileState();
}

class _CreateProfileState extends State<CreateProfile> {
  final name = TextEditingController(), phone = TextEditingController();
  String? error;
  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Set up your technician profile'), actions: [TextButton(onPressed: widget.onSignOut, child: const Text('Sign out', style: TextStyle(color: Colors.white)))]),
        body: ListView(padding: const EdgeInsets.all(20), children: [
          TextField(controller: name, decoration: const InputDecoration(labelText: 'Display name')),
          TextField(controller: phone, keyboardType: TextInputType.phone, decoration: const InputDecoration(labelText: 'Phone')),
          if (error != null) Text(error!, style: const TextStyle(color: Colors.red)),
          const SizedBox(height: 16),
          FilledButton(onPressed: () async {
            try {
              await Api.instance.post('/technicians/me', {'displayName': name.text.trim(), 'phone': phone.text.trim()});
              widget.onCreated();
            } on ApiException catch (e) { setState(() => error = e.message); }
          }, child: const Text('Continue')),
        ]),
      );
}

class NotificationsScreen extends StatefulWidget {
  const NotificationsScreen({super.key});
  @override
  State<NotificationsScreen> createState() => _NotificationsScreenState();
}

class _NotificationsScreenState extends State<NotificationsScreen> {
  late Future<List> f = Api.instance.get<List>('/notifications');
  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Notifications')),
        body: FutureBuilder<List>(
          future: f,
          builder: (c, s) {
            if (s.hasError) return Center(child: Text('${s.error}'));
            if (!s.hasData) return const Center(child: CircularProgressIndicator());
            if (s.data!.isEmpty) return const Center(child: Text('Nothing yet.'));
            return ListView(children: [
              for (final n in s.data!)
                ListTile(
                  title: Text(n['title'], style: TextStyle(fontWeight: n['readAt'] == null ? FontWeight.bold : FontWeight.normal)),
                  subtitle: Text('${n['body']}\n${when(n['createdAt'])}'),
                  isThreeLine: true,
                  onTap: n['readAt'] != null ? null : () async {
                    await Api.instance.post('/notifications/${n['id']}/read');
                    setState(() => f = Api.instance.get<List>('/notifications'));
                  },
                ),
            ]);
          },
        ),
      );
}
