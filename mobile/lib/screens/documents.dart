import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import '../api.dart';
import 'auth.dart';

class DocumentsScreen extends StatefulWidget {
  const DocumentsScreen({super.key});
  @override
  State<DocumentsScreen> createState() => _DocumentsScreenState();
}

class _DocumentsScreenState extends State<DocumentsScreen> {
  late Future<List> f = Api.instance.get<List>('/technicians/me/documents');
  void refresh() => setState(() => f = Api.instance.get<List>('/technicians/me/documents'));
  String kind = 'identity';
  bool busy = false;

  Future<void> upload() async {
    final r = await FilePicker.platform.pickFiles(type: FileType.custom, allowedExtensions: ['pdf', 'jpg', 'jpeg', 'png'], withData: true);
    final file = r?.files.single;
    if (file == null || file.bytes == null) return;
    if (file.size > 5000000) { if (mounted) snack(context, 'File is larger than 5 MB.'); return; }
    setState(() => busy = true);
    try {
      await Api.instance.upload(kind, file.name, file.bytes!);
      refresh();
      if (mounted) snack(context, 'Uploaded. A reviewer will check it.');
    } on ApiException catch (e) {
      if (mounted) snack(context, e.message);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => ListView(padding: const EdgeInsets.all(12), children: [
        const Text('Upload your ID and qualification documents (PDF, JPG or PNG, up to 5 MB). Only you and platform reviewers can see them.'),
        const SizedBox(height: 8),
        Row(children: [
          DropdownButton<String>(value: kind, items: const [
            DropdownMenuItem(value: 'identity', child: Text('Identity')),
            DropdownMenuItem(value: 'qualification', child: Text('Qualification')),
            DropdownMenuItem(value: 'other', child: Text('Other')),
          ], onChanged: (v) => setState(() => kind = v!)),
          const SizedBox(width: 12),
          FilledButton.icon(onPressed: busy ? null : upload, icon: const Icon(Icons.upload_file), label: Text(busy ? 'Uploading…' : 'Choose file')),
        ]),
        const Divider(height: 28),
        FutureBuilder<List>(
          future: f,
          builder: (c, s) {
            if (s.hasError) return Text('${s.error}');
            if (!s.hasData) return const Center(child: CircularProgressIndicator());
            if (s.data!.isEmpty) return const Text('No documents yet.');
            return Column(children: [
              for (final d in s.data!)
                ListTile(
                  leading: const Icon(Icons.description_outlined),
                  title: Text(d['fileName']),
                  subtitle: Text('${d['kind']} · uploaded ${when(d['uploadedAt'])}${d['reviewNote'] != null ? '\nReviewer: ${d['reviewNote']}' : ''}'),
                  isThreeLine: d['reviewNote'] != null,
                  trailing: Chip(label: Text(d['status'])),
                ),
            ]);
          },
        ),
      ]);
}
