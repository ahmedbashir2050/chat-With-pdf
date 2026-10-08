import 'dart:typed_data';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:get/get.dart';

import '../models/chat.dart';
import '../services/api_service.dart';
import '../services/local_store.dart';
import 'auth_controller.dart';

class HomeController extends GetxController {
  final chats = <Chat>[].obs;
  final isLoading = true.obs;
  final isCreating = false.obs;
  final isOffline = false.obs;
  final errorMessage = RxnString();
  final selectedChatId = RxnInt(); // used only in the wide split-view layout
  final uploadProgress = 0.0.obs; // 0.0–1.0, drives UploadProgressDialog

  @override
  void onInit() {
    super.onInit();
    _watchConnectivity();
    loadChats();
  }

  void _watchConnectivity() {
    Connectivity().checkConnectivity().then(
      (r) => isOffline.value = _isNone(r),
    );
    Connectivity().onConnectivityChanged.listen((r) {
      final wasOffline = isOffline.value;
      isOffline.value = _isNone(r);
      // Coming back online: refresh from the server so the cache catches up.
      if (wasOffline && !isOffline.value) loadChats();
    });
  }

  bool _isNone(List<ConnectivityResult> results) =>
      results.isEmpty || results.every((r) => r == ConnectivityResult.none);

  Future<void> loadChats() async {
    isLoading.value = true;
    errorMessage.value = null;

    // Offline-first: show whatever's cached immediately, don't block on network.
    final cached = LocalStore.getCachedChats();
    if (cached.isNotEmpty) chats.value = cached;

    if (isOffline.value) {
      isLoading.value = false;
      return;
    }

    try {
      final fresh = await ApiService.listChats();
      chats.value = fresh;
      await LocalStore.cacheChats(fresh);
      if (selectedChatId.value != null &&
          !fresh.any((c) => c.id == selectedChatId.value)) {
        selectedChatId.value = null;
      }
    } on AuthExpiredException {
      await Get.find<AuthController>().signOut();
    } catch (e) {
      if (cached.isEmpty)
        errorMessage.value = 'Could not reach the server.\n$e';
      // If we have cached data, fail silently — the cache is still shown.
    } finally {
      isLoading.value = false;
    }
  }

  Future<Chat?> createChat(Uint8List bytes, String filename) async {
    isCreating.value = true;
    uploadProgress.value = 0.0;
    try {
      final chat = await ApiService.createChat(
        bytes,
        filename,
        onProgress: (p) => uploadProgress.value = p,
      );
      await loadChats();
      return chat;
    } finally {
      isCreating.value = false;
      uploadProgress.value = 0.0;
    }
  }

  Future<void> deleteChat(Chat chat) async {
    await ApiService.deleteChat(chat.id);
    await LocalStore.removeCachedChat(chat.id);
    if (selectedChatId.value == chat.id) selectedChatId.value = null;
    await loadChats();
  }

  void selectChat(int chatId) => selectedChatId.value = chatId;
}
