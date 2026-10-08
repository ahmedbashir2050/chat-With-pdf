import 'dart:convert';

import 'package:hive_flutter/hive_flutter.dart';

import '../models/chat.dart';
import '../models/message.dart';

/// Caches chats and messages locally so the app has something to show
/// immediately on open and stays usable (read-only) when offline.
/// Stores plain JSON strings in Hive boxes — no generated TypeAdapters,
/// so there's no build_runner step and it works identically on Web
/// (IndexedDB-backed) and Android/iOS (file-backed).
///
/// Every key is namespaced by the signed-in user's id. This matters on a
/// shared device: without it, signing out and signing back in as a
/// different Google account would still show the previous user's cached
/// chats until the next successful network refresh.
class LocalStore {
  static const _chatsBoxName = 'chats_box';
  static const _messagesBoxName = 'messages_box';

  static late Box<String> _chatsBox;
  static late Box<String> _messagesBox;

  /// Set once after sign-in/session-restore; null while logged out.
  static int? _currentUserId;

  static Future<void> init() async {
    await Hive.initFlutter();
    _chatsBox = await Hive.openBox<String>(_chatsBoxName);
    _messagesBox = await Hive.openBox<String>(_messagesBoxName);
  }

  static void setCurrentUser(int? userId) => _currentUserId = userId;

  static String _scoped(String key) => '${_currentUserId ?? 'anon'}:$key';

  /// Wipes ALL cached data for every account that's ever used this device
  /// — used on sign-out so nothing lingers for whoever signs in next.
  static Future<void> clearAll() async {
    await _chatsBox.clear();
    await _messagesBox.clear();
  }

  // ---------------- Chats ----------------

  static Future<void> cacheChats(List<Chat> chats) async {
    final encoded = jsonEncode(chats.map((c) => c.toJson()).toList());
    await _chatsBox.put(_scoped('list'), encoded);
  }

  static List<Chat> getCachedChats() {
    final raw = _chatsBox.get(_scoped('list'));
    if (raw == null) return [];
    final List<dynamic> data = jsonDecode(raw);
    return data.map((e) => Chat.fromJson(e as Map<String, dynamic>)).toList();
  }

  static Future<void> removeCachedChat(int chatId) async {
    final chats = getCachedChats().where((c) => c.id != chatId).toList();
    await cacheChats(chats);
    await _messagesBox.delete(_scoped(chatId.toString()));
  }

  // ---------------- Messages ----------------

  static Future<void> cacheMessages(int chatId, List<ChatMessageModel> messages) async {
    final encoded = jsonEncode(messages.map((m) => m.toJson()).toList());
    await _messagesBox.put(_scoped(chatId.toString()), encoded);
  }

  static List<ChatMessageModel> getCachedMessages(int chatId) {
    final raw = _messagesBox.get(_scoped(chatId.toString()));
    if (raw == null) return [];
    final List<dynamic> data = jsonDecode(raw);
    return data.map((e) => ChatMessageModel.fromJson(e as Map<String, dynamic>)).toList();
  }
}
