import 'package:flutter/material.dart';
import '../api.dart';

void snack(BuildContext c, String m) => ScaffoldMessenger.of(c).showSnackBar(SnackBar(content: Text(m)));

class LoginScreen extends StatefulWidget {
  final VoidCallback onDone;
  const LoginScreen({super.key, required this.onDone});
  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final email = TextEditingController(), password = TextEditingController(), name = TextEditingController(), code = TextEditingController();
  bool register = false, busy = false;
  String? mfaToken, error;

  Future<void> submit() async {
    setState(() { busy = true; error = null; });
    try {
      final api = Api.instance;
      if (mfaToken != null) {
        final r = await api.post<Map>('/auth/mfa/verify', {'mfaToken': mfaToken, 'code': code.text.trim()});
        await api.setToken(r['token']);
        widget.onDone();
        return;
      }
      if (register) {
        await api.post('/auth/register', {'email': email.text.trim(), 'password': password.text, 'displayName': name.text.trim()});
      }
      final r = await api.post<Map>('/auth/login', {'email': email.text.trim(), 'password': password.text});
      if (r['mfaRequired'] == true) {
        setState(() => mfaToken = r['mfaToken']);
      } else {
        await api.setToken(r['token']);
        widget.onDone();
      }
    } on ApiException catch (e) {
      setState(() => error = e.message);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Duale BuildLink')),
        body: ListView(padding: const EdgeInsets.all(20), children: [
          if (mfaToken != null) ...[
            const Text('Enter the 6-digit code from your authenticator app, or a recovery code.'),
            TextField(controller: code, decoration: const InputDecoration(labelText: 'Code'), autofocus: true),
          ] else ...[
            if (register) TextField(controller: name, decoration: const InputDecoration(labelText: 'Your name')),
            TextField(controller: email, keyboardType: TextInputType.emailAddress, decoration: const InputDecoration(labelText: 'Email')),
            TextField(controller: password, obscureText: true, decoration: InputDecoration(labelText: register ? 'Password (12+ characters)' : 'Password')),
          ],
          if (error != null) Padding(padding: const EdgeInsets.only(top: 8), child: Text(error!, style: const TextStyle(color: Colors.red))),
          const SizedBox(height: 16),
          FilledButton(onPressed: busy ? null : submit, child: Text(mfaToken != null ? 'Verify' : register ? 'Create account' : 'Sign in')),
          if (mfaToken == null) ...[
            TextButton(onPressed: () => setState(() => register = !register), child: Text(register ? 'I already have an account' : 'Create an account')),
            TextButton(onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const RecoverScreen())), child: const Text('Forgot password?')),
          ],
        ]),
      );
}

class RecoverScreen extends StatefulWidget {
  const RecoverScreen({super.key});
  @override
  State<RecoverScreen> createState() => _RecoverScreenState();
}

class _RecoverScreenState extends State<RecoverScreen> {
  final email = TextEditingController(), token = TextEditingController(), pw = TextEditingController(), code = TextEditingController();
  bool sent = false, busy = false;
  String? error;

  Future<void> run(Future<void> Function() f) async {
    setState(() { busy = true; error = null; });
    try { await f(); } on ApiException catch (e) { setState(() => error = e.message); } finally { if (mounted) setState(() => busy = false); }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Account recovery')),
        body: ListView(padding: const EdgeInsets.all(20), children: [
          if (!sent) ...[
            TextField(controller: email, keyboardType: TextInputType.emailAddress, decoration: const InputDecoration(labelText: 'Email')),
            const SizedBox(height: 12),
            FilledButton(onPressed: busy ? null : () => run(() async {
              await Api.instance.post('/auth/recovery/request', {'email': email.text.trim()});
              setState(() => sent = true);
            }), child: const Text('Send recovery token')),
          ] else ...[
            const Text('If the account exists, a recovery token was sent. Enter it below.'),
            TextField(controller: token, decoration: const InputDecoration(labelText: 'Recovery token')),
            TextField(controller: pw, obscureText: true, decoration: const InputDecoration(labelText: 'New password (12+ characters)')),
            TextField(controller: code, decoration: const InputDecoration(labelText: 'Authenticator or recovery code (if you use two-factor)')),
            const SizedBox(height: 12),
            FilledButton(onPressed: busy ? null : () => run(() async {
              await Api.instance.post('/auth/recovery/reset', {'token': token.text.trim(), 'newPassword': pw.text, if (code.text.isNotEmpty) 'code': code.text.trim()});
              if (!mounted) return;
              snack(context, 'Password changed. Sign in with the new password.');
              Navigator.pop(context);
            }), child: const Text('Reset password')),
          ],
          if (error != null) Padding(padding: const EdgeInsets.only(top: 8), child: Text(error!, style: const TextStyle(color: Colors.red))),
        ]),
      );
}
