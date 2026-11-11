import 'dart:convert';
import 'dart:math';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;

/// Set at build time: flutter run --dart-define=API_BASE=https://api.example.com
const apiBase = String.fromEnvironment('API_BASE', defaultValue: 'http://10.0.2.2:8080');

class ApiException implements Exception {
  final int status;
  final String message;
  ApiException(this.status, this.message);
  @override
  String toString() => message;
}

class Api {
  static final Api instance = Api._();
  Api._();

  final _store = const FlutterSecureStorage();
  String? _token;
  void Function()? onSignedOut;

  Future<void> load() async => _token = await _store.read(key: 'token');
  bool get signedIn => _token != null;
  Future<void> setToken(String? t) async {
    _token = t;
    t == null ? await _store.delete(key: 'token') : await _store.write(key: 'token', value: t);
  }

  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        if (_token != null) 'Authorization': 'Bearer $_token',
      };

  dynamic _parse(http.Response r) {
    final body = r.body.isEmpty ? null : jsonDecode(r.body);
    if (r.statusCode >= 200 && r.statusCode < 300) return body;
    if (r.statusCode == 401 && _token != null) {
      setToken(null);
      onSignedOut?.call();
    }
    final msg = body is Map ? (body['error'] ?? body['title'] ?? 'Request failed') : 'Request failed';
    throw ApiException(r.statusCode, '$msg');
  }

  Future<T> _send<T>(Future<http.Response> Function() f) async {
    try {
      return _parse(await f().timeout(const Duration(seconds: 20))) as T;
    } on ApiException {
      rethrow;
    } catch (_) {
      // Unreliable mobile networks: surface a plain message and let the user retry.
      throw ApiException(0, 'No connection. Check your network and try again.');
    }
  }

  Uri _u(String p) => Uri.parse('$apiBase$p');
  Future<T> get<T>(String p) => _send(() => http.get(_u(p), headers: _headers));
  Future<T> post<T>(String p, [Object? body]) => _send(() => http.post(_u(p), headers: _headers, body: jsonEncode(body ?? {})));
  Future<T> put<T>(String p, Object body) => _send(() => http.put(_u(p), headers: _headers, body: jsonEncode(body)));
  Future<void> delete(String p) => _send<dynamic>(() => http.delete(_u(p), headers: _headers));

  /// A new random key per user action. Re-sending the SAME key after a dropped connection is safe: the server replays the result.
  static String newKey() { final r = Random.secure(); return List.generate(16, (_) => r.nextInt(256).toRadixString(16).padLeft(2, '0')).join(); }

  Future<T> postIdem<T>(String p, Object body, String key) =>
      _send(() => http.post(_u(p), headers: {..._headers, 'Idempotency-Key': key}, body: jsonEncode(body)));

  Future<void> uploadEvidence(String assignmentId, String kind, String filename, List<int> bytes, String key) async {
    final req = http.MultipartRequest('POST', _u('/technicians/me/assignments/$assignmentId/evidence'))
      ..headers['Authorization'] = 'Bearer $_token'
      ..headers['Idempotency-Key'] = key
      ..fields['kind'] = kind
      ..files.add(http.MultipartFile.fromBytes('file', bytes, filename: filename));
    try {
      _parse(await http.Response.fromStream(await req.send().timeout(const Duration(seconds: 60))));
    } on ApiException {
      rethrow;
    } catch (_) {
      throw ApiException(0, 'Upload failed. Check your network and try again.');
    }
  }

  Future<void> upload(String kind, String filename, List<int> bytes, {String? expiresOn}) async {
    final req = http.MultipartRequest('POST', _u('/technicians/me/documents'))
      ..headers['Authorization'] = 'Bearer $_token'
      ..fields['kind'] = kind
      ..files.add(http.MultipartFile.fromBytes('file', bytes, filename: filename));
    if (expiresOn != null) req.fields['expiresOn'] = expiresOn;
    try {
      final res = await http.Response.fromStream(await req.send().timeout(const Duration(seconds: 60)));
      _parse(res);
    } on ApiException {
      rethrow;
    } catch (_) {
      throw ApiException(0, 'Upload failed. Check your network and try again.');
    }
  }
}

String when(String? iso) => iso == null ? '' : DateTime.parse(iso).toLocal().toString().substring(0, 16);
