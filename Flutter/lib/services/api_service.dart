import 'dart:convert';
import 'dart:developer';
import 'dart:typed_data';

import 'package:dio/dio.dart' as dio;
import 'package:http/http.dart' as http;
import 'package:http_parser/http_parser.dart';

import '../config.dart';
import '../models/chat.dart';
import '../models/message.dart';
import 'auth_service.dart';

/// Thrown when the backend rejects our session token (missing, expired, or
/// otherwise invalid). Callers can catch this specifically to force a
/// sign-out rather than showing a generic "request failed" error.
class AuthExpiredException implements Exception {
  final String message;
  AuthExpiredException([
    this.message = 'Session expired. Please sign in again.',
  ]);
  @override
  String toString() => message;
}

class ApiService {
  static Map<String, String> _authHeaders({Map<String, String>? extra}) {
    final token = AuthService.currentToken;
    return {if (token != null) 'Authorization': 'Bearer $token', ...?extra};
  }

  static void _throwIfUnauthorized(http.Response response) {
    if (response.statusCode == 401) throw AuthExpiredException();
  }

  static final dio.Dio _dio = dio.Dio();

  /// Uploads a PDF to create a brand-new chat, scoped to the signed-in
  /// user, reporting real upload progress (0.0–1.0) as it goes — used to
  /// drive an actual percentage in the UI rather than an indeterminate
  /// spinner. The backend then extracts, chunks, and embeds the document
  /// (that part has no meaningful "percent" of its own, so progress caps
  /// at ~99% until the response actually comes back).
  static Future<Chat> createChat(
    Uint8List bytes,
    String filename, {
    void Function(double progress)? onProgress,
  }) async {
    final formData = dio.FormData.fromMap({
      'file': dio.MultipartFile.fromBytes(
        bytes,
        filename: filename,
        contentType: MediaType('application', 'pdf'),
      ),
    });

    try {
      final response = await _dio.post(
        '$kApiBaseUrl/chats',
        data: formData,
        options: dio.Options(headers: _authHeaders()),
        onSendProgress: (sent, total) {
          if (total > 0 && onProgress != null) {
            // Cap at 0.99 while the upload itself finishes — the last
            // stretch is server-side processing (extract/chunk/embed),
            // which has no byte-progress of its own.
            onProgress((sent / total).clamp(0.0, 0.99));
          }
        },
      );
      onProgress?.call(1.0);
      return Chat.fromJson(response.data);
    } on dio.DioException catch (e) {
      if (e.response?.statusCode == 401) throw AuthExpiredException();
      throw Exception(
        'Failed to create chat: ${e.response?.data ?? e.message}',
      );
    }
  }

  static Future<List<Chat>> listChats() async {
    final response = await http.get(
      Uri.parse('$kApiBaseUrl/chats'),
      headers: _authHeaders(),
    );
    _throwIfUnauthorized(response);
    if (response.statusCode != 200) {
      throw Exception('Failed to load chats: ${response.body}');
    }
    final List<dynamic> data = jsonDecode(response.body);
    return data.map((e) => Chat.fromJson(e)).toList();
  }

  static Future<void> deleteChat(int chatId) async {
    final response = await http.delete(
      Uri.parse('$kApiBaseUrl/chats/$chatId'),
      headers: _authHeaders(),
    );
    _throwIfUnauthorized(response);
    if (response.statusCode != 200) {
      throw Exception('Failed to delete chat: ${response.body}');
    }
  }

  /// Swaps in an updated PDF for an existing chat. Server discards old
  /// chunks/embeddings and reprocesses; message history is kept.
  static Future<Chat> replaceResource(
    int chatId,
    Uint8List bytes,
    String filename, {
    void Function(double progress)? onProgress,
  }) async {
    final formData = dio.FormData.fromMap({
      'file': dio.MultipartFile.fromBytes(
        bytes,
        filename: filename,
        contentType: MediaType('application', 'pdf'),
      ),
    });

    try {
      final response = await _dio.put(
        '$kApiBaseUrl/chats/$chatId/resource',
        data: formData,
        options: dio.Options(headers: _authHeaders()),
        onSendProgress: (sent, total) {
          if (total > 0 && onProgress != null) {
            onProgress((sent / total).clamp(0.0, 0.99));
          }
        },
      );
      onProgress?.call(1.0);
      return Chat.fromJson(response.data);
    } on dio.DioException catch (e) {
      if (e.response?.statusCode == 401) throw AuthExpiredException();
      throw Exception(
        'Failed to update resource: ${e.response?.data ?? e.message}',
      );
    }
  }

  static Future<List<ChatMessageModel>> getMessages(int chatId) async {
    final response = await http.get(
      Uri.parse('$kApiBaseUrl/chats/$chatId/messages'),
      headers: _authHeaders(),
    );
    _throwIfUnauthorized(response);
    if (response.statusCode != 200) {
      throw Exception('Failed to load messages: ${response.body}');
    }
    final List<dynamic> data = jsonDecode(response.body);
    return data.map((e) => ChatMessageModel.fromJson(e)).toList();
  }

  /// Sends a question. The backend decides everything: whether it's a
  /// summary request or a specific question, what retrieval strategy to
  /// use, AND how long the answer should be — inferred from the message
  /// itself (explicit phrasing, refinement of the last answer, or the
  /// question's own shape), the same way ChatGPT/NotebookLM do it with no
  /// length toggle in the UI. It also saves both messages server-side.
  static Future<AskResult> sendMessage(int chatId, String question) async {
    final response = await http.post(
      Uri.parse('$kApiBaseUrl/chats/$chatId/messages'),
      headers: _authHeaders(extra: {'Content-Type': 'application/json'}),
      body: jsonEncode({'question': question}),
    );
    _throwIfUnauthorized(response);
    if (response.statusCode != 200) {
      throw Exception('Failed to send message: ${response.body}');
    }
    final data = jsonDecode(response.body);

    final result = AskResult.fromJson(data);

    log('========== PARSED RESULT =============');
    log('Reply: ${result.reply}');
    log('Confidence: ${result.confidenceScore}');
    log('Citations count: ${result.citations.length}');

    for (final citation in result.citations) {
      log('--- Citation ---');
      log('Physical page: ${citation.physicalPage}');
      log('Chapter: ${citation.chapter}');
      log('Section: ${citation.section}');
      log('Heading: ${citation.heading}');
    }

    log('=======================================');

    return result;
  }
}

/// The backend's full answer payload — reply text plus the metadata that
/// used to be silently dropped (confidence_score) or only ever surfaced
/// indirectly (citations are also parsed inline from the reply text itself
/// by MessageBody, via the [p. X] markers — this structured list is kept
/// here too for a future PDF-viewer/"jump to source" screen, since it
/// carries page/section/bbox that inline parsing can't).
class AskResult {
  final String reply;
  final double confidenceScore;
  final List<CitationInfo> citations;

  AskResult({
    required this.reply,
    required this.confidenceScore,
    required this.citations,
  });

  factory AskResult.fromJson(Map<String, dynamic> json) => AskResult(
    reply: json['reply'] as String? ?? json['answer'],
    confidenceScore: (json['confidence_score'] as num?)?.toDouble() ?? 1.0,
    citations: (json['citations'] as List<dynamic>? ?? [])
        .map((c) => CitationInfo.fromJson(c as Map<String, dynamic>))
        .toList(),
  );
}

class CitationInfo {
  final int physicalPage;

  final String? chapter;
  final String? section;
  final String? heading;

  CitationInfo({
    required this.physicalPage,
    this.chapter,
    this.section,
    this.heading,
  });

  factory CitationInfo.fromJson(Map<String, dynamic> json) => CitationInfo(
    physicalPage: json['physical_page'] as int,
    chapter: json['chapter'] as String?,
    section: json['section'] as String?,
    heading: json['heading'] as String?,
  );
}
