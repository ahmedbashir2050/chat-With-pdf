import 'dart:developer';
import 'dart:typed_data';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:flutter/widgets.dart';
import 'package:get/get.dart';

import '../models/message.dart';
import '../services/api_service.dart';
import '../services/local_store.dart';
import 'auth_controller.dart';

class ChatController extends GetxController {
  final int chatId;
  ChatController({required this.chatId});

  // ── Message state ──────────────────────────────────────────────────────
  final messages = <ChatMessageModel>[].obs;
  final isSending = false.obs;
  final isLoadingHistory = true.obs;
  final isOffline = false.obs;
  final uploadProgress = 0.0.obs;

  final overview = ''.obs;

  final inputController = TextEditingController();
  final scrollController = ScrollController();

  @override
  void onInit() {
    super.onInit();
    _watchConnectivity();
    _loadHistory();
  }

  @override
  void onClose() {
    inputController.dispose();
    scrollController.dispose();
    super.onClose();
  }

  void _watchConnectivity() {
    Connectivity().checkConnectivity().then(
      (r) => isOffline.value = _isNone(r),
    );

    Connectivity().onConnectivityChanged.listen(
      (r) => isOffline.value = _isNone(r),
    );
  }

  bool _isNone(List<ConnectivityResult> results) =>
      results.isEmpty || results.every((r) => r == ConnectivityResult.none);

  // ── Add document overview as first message ─────────────────────────────

  void _addOverviewMessage(String chatOverview) {
    final text = chatOverview.trim();

    if (text.isEmpty) return;

    overview.value = text;

    // Prevent duplicate overview messages.
    final alreadyExists = messages.any((message) => message.id == -2);

    if (alreadyExists) {
      return;
    }
    bool containsArabic(String text) {
      final arabicRegex = RegExp(r'[\u0600-\u06FF]');
      return arabicRegex.hasMatch(text);
    }

    String getOverviewTitle(String text) {
      if (containsArabic(text)) {
        return '## 📄 نظرة عامة على المستند بالكامل';
      }

      return '## 📄 Overview of the Entire Document';
    }

    final overviewTitle = getOverviewTitle(text);
    messages.insert(
      0,
      ChatMessageModel(
        id: -2,
        role: 'assistant',
        content: '$overviewTitle\n\n$text',
        createdAt: DateTime.now(),
      ),
    );
  }

  // ── History ───────────────────────────────────────────────────────────

  Future<void> _loadHistory() async {
    isLoadingHistory.value = true;

    // Offline-first: cached messages render immediately.
    final cached = LocalStore.getCachedMessages(chatId);

    if (cached.isNotEmpty) {
      messages.value = cached;
      _scrollToBottom();
    }

    if (isOffline.value) {
      isLoadingHistory.value = false;
      return;
    }

    try {
      // Load chat metadata so we can get the overview.
      final chats = await ApiService.listChats();

      final chat = chats.firstWhere((chat) => chat.id == chatId);

      // Add overview as the first message if it exists.
      _addOverviewMessage(chat.overview);

      // Load actual conversation history.
      final fresh = await ApiService.getMessages(chatId);

      // Keep overview as the first message.
      messages.value = fresh;

      _addOverviewMessage(chat.overview);

      await LocalStore.cacheMessages(chatId, messages);

      _scrollToBottom();
    } on AuthExpiredException {
      await Get.find<AuthController>().signOut();
    } catch (_) {
      // Network hiccup with a non-empty cache already shown — fail quietly.
    } finally {
      isLoadingHistory.value = false;
    }
  }

  Future<void> _persist() => LocalStore.cacheMessages(chatId, messages);

  // ── Send typed text ─────────────────────────────────────────────────────

  Future<void> sendQuestion() async {
    final question = inputController.text.trim();

    if (question.isEmpty || isSending.value) return;

    inputController.clear();

    await _ask(question);
  }

  // ── Core ask ───────────────────────────────────────────────────────────

  Future<void> _ask(String question) async {
    if (isOffline.value) {
      Get.snackbar(
        'Offline',
        "You're offline — connect to send a question.",
        snackPosition: SnackPosition.TOP,
      );
      return;
    }

    isSending.value = true;

    final userMsg = ChatMessageModel(
      id: -1,
      role: 'user',
      content: question,
      createdAt: DateTime.now(),
    );

    messages.add(userMsg);
    _scrollToBottom();

    try {
      final result = await ApiService.sendMessage(chatId, question);
      log("sendQuestion:::: $result");
      messages.add(
        ChatMessageModel(
          id: -1,
          role: 'assistant',
          content: result.reply,
          createdAt: DateTime.now(),
          confidenceScore: result.confidenceScore,
        ),
      );

      await _persist();
    } on AuthExpiredException {
      messages.removeLast();

      await Get.find<AuthController>().signOut();
    } catch (e) {
      messages.add(
        ChatMessageModel(
          id: -1,
          role: 'assistant',
          content: "Something went wrong: $e",
          createdAt: DateTime.now(),
        ),
      );
    } finally {
      isSending.value = false;
      _scrollToBottom();
    }
  }

  // ── Replace PDF resource ───────────────────────────────────────────────

  Future<void> replaceResource(Uint8List bytes, String filename) async {
    uploadProgress.value = 0.0;

    try {
      final chat = await ApiService.replaceResource(
        chatId,
        bytes,
        filename,
        onProgress: (p) => uploadProgress.value = p,
      );

      // Update the current overview.
      overview.value = chat.overview;

      // Remove the old overview message if one exists.
      messages.removeWhere((message) => message.id == -2);

      // Add the new overview as the FIRST message.
      _addOverviewMessage(chat.overview);

      // Save the updated local history.
      await _persist();

      Get.snackbar('Updated', 'Resource updated for this chat.');

      _scrollToBottom();
    } finally {
      uploadProgress.value = 0.0;
    }
  }

  void _scrollToBottom() {
    Future.delayed(const Duration(milliseconds: 100), () {
      if (scrollController.hasClients) {
        scrollController.animateTo(
          scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 250),
          curve: Curves.easeOut,
        );
      }
    });
  }
}

// import 'dart:typed_data';

// import 'package:connectivity_plus/connectivity_plus.dart';
// import 'package:flutter/widgets.dart';
// import 'package:get/get.dart';

// import '../models/message.dart';
// import '../services/api_service.dart';
// import '../services/local_store.dart';
// import 'auth_controller.dart';

// class ChatController extends GetxController {
//   final int chatId;
//   ChatController({required this.chatId});

//   // ── Message state ──────────────────────────────────────────────────────
//   final messages = <ChatMessageModel>[].obs;
//   final isSending = false.obs;
//   final isLoadingHistory = true.obs;
//   final isOffline = false.obs;
//   final uploadProgress =
//       0.0.obs; // 0.0–1.0, drives UploadProgressDialog when replacing the PDF
//   final overview = ''.obs;
//   // Answer length used to be a manual toggle here; the backend now infers
//   // it from the message itself, so there's nothing to track client-side.
//   final inputController = TextEditingController();
//   final scrollController = ScrollController();

//   @override
//   void onInit() {
//     super.onInit();
//     _watchConnectivity();
//     _loadHistory();
//   }

//   @override
//   void onClose() {
//     inputController.dispose();
//     scrollController.dispose();
//     super.onClose();
//   }

//   void _watchConnectivity() {
//     Connectivity().checkConnectivity().then(
//       (r) => isOffline.value = _isNone(r),
//     );
//     Connectivity().onConnectivityChanged.listen(
//       (r) => isOffline.value = _isNone(r),
//     );
//   }

//   bool _isNone(List<ConnectivityResult> results) =>
//       results.isEmpty || results.every((r) => r == ConnectivityResult.none);

//   // ── Add document overview as first message ─────────────────────────────

//   void _addOverviewMessage(String chatOverview) {
//     final text = chatOverview.trim();
//     if (text.isEmpty) return;
//     overview.value = text;
//     // Prevent duplicate overview messages.
//     final alreadyExists = messages.any((message) => message.id == -2);
//     if (alreadyExists) {
//       return;
//     }
//     messages.insert(
//       0,
//       ChatMessageModel(
//         id: -2,
//         role: 'assistant',
//         content: text,
//         createdAt: DateTime.now(),
//       ),
//     );
//   }

//   // ── History ───────────────────────────────────────────────────────────

//   Future<void> _loadHistory() async {
//     isLoadingHistory.value = true;

//     // Offline-first: cached messages render immediately.
//     final cached = LocalStore.getCachedMessages(chatId);
//     if (cached.isNotEmpty) {
//       messages.value = cached;
//       _scrollToBottom();
//     }

//     if (isOffline.value) {
//       isLoadingHistory.value = false;
//       return;
//     }

//     try {
//       final fresh = await ApiService.getMessages(chatId);
//       messages.value = fresh;
//       await LocalStore.cacheMessages(chatId, fresh);

//       _scrollToBottom();
//     } on AuthExpiredException {
//       await Get.find<AuthController>().signOut();
//     } catch (_) {
//       // Network hiccup with a non-empty cache already shown — fail quietly.
//     } finally {
//       isLoadingHistory.value = false;
//     }
//   }

//   Future<void> _persist() => LocalStore.cacheMessages(chatId, messages);

//   // ── Send typed text ─────────────────────────────────────────────────────

//   Future<void> sendQuestion() async {
//     final question = inputController.text.trim();
//     if (question.isEmpty || isSending.value) return;
//     inputController.clear();
//     await _ask(question);
//   }

//   // ── Core ask ─────────────────────────────────────────────────────────────

//   Future<void> _ask(String question) async {
//     if (isOffline.value) {
//       Get.snackbar(
//         'Offline',
//         "You're offline — connect to send a question.",
//         snackPosition: SnackPosition.TOP,
//       );
//       return;
//     }

//     isSending.value = true;
//     final userMsg = ChatMessageModel(
//       id: -1,
//       role: 'user',
//       content: question,
//       createdAt: DateTime.now(),
//     );
//     messages.add(userMsg);
//     _scrollToBottom();

//     try {
//       final result = await ApiService.sendMessage(chatId, question);

//       messages.add(
//         ChatMessageModel(
//           id: -1,
//           role: 'assistant',
//           content: result.reply,
//           createdAt: DateTime.now(),
//           confidenceScore: result.confidenceScore,
//         ),
//       );
//       await _persist();
//     } on AuthExpiredException {
//       messages.removeLast(); // drop the optimistic user bubble; nothing was actually sent
//       await Get.find<AuthController>().signOut();
//     } catch (e) {
//       messages.add(
//         ChatMessageModel(
//           id: -1,
//           role: 'assistant',
//           content: "Something went wrong: $e",
//           createdAt: DateTime.now(),
//         ),
//       );
//     } finally {
//       isSending.value = false;
//       _scrollToBottom();
//     }
//   }

//   // ── Misc ──────────────────────────────────────────────────────────────

//   Future<void> replaceResource(Uint8List bytes, String filename) async {
//     uploadProgress.value = 0.0;
//     try {
//       final chat = await ApiService.replaceResource(
//         chatId,
//         bytes,
//         filename,
//         onProgress: (p) => uploadProgress.value = p,
//       );
//       // Update the current overview.
//       overview.value = chat.overview;
//       // Remove the old overview message if one exists.
//       messages.removeWhere((message) => message.id == -2);
//       // Add the new overview as the FIRST message.
//       _addOverviewMessage(chat.overview);
//       // Save the updated local history.
//       await _persist();

//       Get.snackbar('Updated', 'Resource updated for this chat.');
//     } finally {
//       uploadProgress.value = 0.0;
//     }
//   }

//   void _scrollToBottom() {
//     Future.delayed(const Duration(milliseconds: 100), () {
//       if (scrollController.hasClients) {
//         scrollController.animateTo(
//           scrollController.position.maxScrollExtent,
//           duration: const Duration(milliseconds: 250),
//           curve: Curves.easeOut,
//         );
//       }
//     });
//   }
// }
