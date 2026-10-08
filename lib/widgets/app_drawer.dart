import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:get/get.dart';

import '../controllers/home_controller.dart';
import '../models/chat.dart';
import '../theme/app_theme.dart';
import '../screens/chat_screen.dart';
import 'chat_list_tile.dart';
import 'upload_progress_dialog.dart';
import 'user_profile_tile.dart';

/// Same idea as ChatGPT's mobile drawer: a "New chat" action pinned at the
/// top, then the full conversation history below. Reuses whatever
/// HomeController is already registered (HomeScreen creates it at startup),
/// so opening the drawer from inside any chat sees the same live list.
class AppDrawer extends StatelessWidget {
  final int? currentChatId;
  const AppDrawer({super.key, this.currentChatId});

  Future<void> _startNewChat(BuildContext context, HomeController ctrl) async {
    Navigator.pop(context); // close the drawer first

    final result = await FilePicker.pickFiles(
      type: FileType.custom,
      allowedExtensions: ['pdf'],
      withData: true,
    );
    if (result == null || result.files.single.bytes == null) return;

    // By now the drawer has fully closed and its own BuildContext is gone
    // — using it here was the bug (the dialog silently never showed).
    // Get.context is GetX's own root context, which stays valid regardless
    // of the drawer's lifecycle.
    final rootContext = Get.context;
    if (rootContext == null) return;
    final dialogFuture = UploadProgressDialog.show(
      rootContext,
      ctrl.uploadProgress,
    );

    try {
      final chat = await ctrl.createChat(
        result.files.single.bytes!,
        result.files.single.name,
      );
      Get.back(); // close the progress dialog
      if (chat == null) return;
      Get.off(() => ChatScreen(chatId: chat.id, title: chat.title));
    } catch (e) {
      Get.back();
      Get.snackbar('Upload failed', '$e');
    }
    await dialogFuture;
  }

  @override
  Widget build(BuildContext context) {
    final ctrl = Get.isRegistered<HomeController>()
        ? Get.find<HomeController>()
        : Get.put(HomeController());

    return Drawer(
      backgroundColor: AppColors.surface,
      child: SafeArea(
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
              child: Row(
                children: [
                  Icon(
                    Icons.auto_awesome,
                    color: AppColors.accentGreen,
                    size: 20,
                  ),
                  const SizedBox(width: 10),
                  Text(
                    'Chat with PDF',
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                ],
              ),
            ),
            const SizedBox(height: 4),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12),
              child: NewChatTile(onTap: () => _startNewChat(context, ctrl)),
            ),
            const SizedBox(height: 8),
            const Divider(height: 1),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 6),
              child: Align(
                alignment: Alignment.centerLeft,
                child: Text(
                  'RECENT',
                  style: TextStyle(
                    color: AppColors.textFaint,
                    fontSize: 11,
                    letterSpacing: 0.6,
                  ),
                ),
              ),
            ),
            Expanded(
              child: Obx(() {
                if (ctrl.chats.isEmpty) {
                  return Padding(
                    padding: EdgeInsets.all(24),
                    child: Text(
                      'No conversations yet',
                      style: TextStyle(
                        color: AppColors.textFaint,
                        fontSize: 13,
                      ),
                    ),
                  );
                }
                return ListView.separated(
                  padding: const EdgeInsets.symmetric(horizontal: 10),
                  itemCount: ctrl.chats.length,
                  separatorBuilder: (_, __) => const SizedBox(height: 2),
                  itemBuilder: (context, index) {
                    final chat = ctrl.chats[index];
                    return ChatListTile(
                      chat: chat,
                      selected: chat.id == currentChatId,
                      onTap: () {
                        Navigator.pop(context); // close the drawer
                        if (chat.id != currentChatId) {
                          // Deferred to the next microtask so the drawer's own
                          // closing route transition fully resolves first —
                          // calling Get.off() in the same synchronous tick as
                          // the pop above could race with it on the navigator
                          // stack and silently fail to replace the screen.
                          if (!context.mounted) return;

                          Navigator.pushReplacement(
                            context,
                            MaterialPageRoute(
                              builder: (context) => ChatScreen(
                                chatId: chat.id,
                                title: chat.title,
                              ),
                            ),
                          );
                        }
                      },
                      onDelete: () => _confirmDelete(context, ctrl, chat),
                    );
                  },
                );
              }),
            ),
            const UserProfileTile(),
          ],
        ),
      ),
    );
  }

  Future<void> _confirmDelete(
    BuildContext context,
    HomeController ctrl,
    Chat chat,
  ) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        backgroundColor: AppColors.surface,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: const Text('Delete chat?'),
        content: Text('This removes "${chat.title}" and its message history.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            child: Text('Delete', style: TextStyle(color: AppColors.dangerRed)),
          ),
        ],
      ),
    );
    if (confirmed == true) {
      await ctrl.deleteChat(chat);
      if (chat.id == currentChatId && context.mounted) {
        Navigator.of(context).popUntil((r) => r.isFirst);
      }
    }
  }
}
