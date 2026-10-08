import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:get/get.dart';

import '../controllers/auth_controller.dart';
import '../controllers/home_controller.dart';
import '../models/chat.dart';
import '../theme/app_theme.dart';
import '../widgets/app_drawer.dart';
import '../widgets/chat_list_tile.dart';
import '../widgets/empty_state.dart';
import '../widgets/offline_banner.dart';
import '../widgets/responsive.dart';
import '../widgets/upload_progress_dialog.dart';
import '../widgets/user_profile_tile.dart';
import 'chat_screen.dart';

class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key});

  HomeController _controller() {
    if (!Get.isRegistered<HomeController>()) Get.put(HomeController());
    return Get.find<HomeController>();
  }

  Future<void> _createNewChat(BuildContext context, HomeController ctrl) async {
    final result = await FilePicker.pickFiles(
      type: FileType.custom,
      allowedExtensions: ['pdf'],
      withData: true,
    );
    if (result == null || result.files.single.bytes == null) return;

    final file = result.files.single;
    if (!context.mounted) return;
    final dialogFuture = UploadProgressDialog.show(
      context,
      ctrl.uploadProgress,
    );

    try {
      final chat = await ctrl.createChat(file.bytes!, file.name);
      if (context.mounted)
        Navigator.of(
          context,
          rootNavigator: true,
        ).pop(); // close progress dialog
      if (chat == null) return;
      if (isWide(context)) {
        ctrl.selectChat(chat.id);
      } else {
        Get.to(() => ChatScreen(chatId: chat.id, title: chat.title));
      }
    } catch (e) {
      if (context.mounted) Navigator.of(context, rootNavigator: true).pop();
      Get.snackbar('Upload failed', '$e');
    }
    await dialogFuture; // avoid an unawaited-future lint; resolves once popped above
  }

  Future<void> _deleteChat(
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
      try {
        await ctrl.deleteChat(chat);
      } catch (e) {
        Get.snackbar('Delete failed', '$e');
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final ctrl = _controller();
    return isWide(context)
        ? _buildWide(context, ctrl)
        : _buildNarrow(context, ctrl);
  }

  Widget _buildNarrow(BuildContext context, HomeController ctrl) {
    return Scaffold(
      drawer: const AppDrawer(),
      appBar: AppBar(
        leading: Builder(
          builder: (ctx) => IconButton(
            icon: const Icon(Icons.menu),
            onPressed: () => Scaffold.of(ctx).openDrawer(),
            tooltip: 'Chats',
          ),
        ),
        title: const Text('chat with pdf'),
        actions: [
          Obx(
            () => IconButton(
              icon: const Icon(Icons.refresh),
              onPressed: ctrl.isLoading.value ? null : ctrl.loadChats,
            ),
          ),
          _AvatarMenuButton(),
          const SizedBox(width: 4),
        ],
      ),
      body: Column(
        children: [
          Obx(
            () => ctrl.isOffline.value
                ? const OfflineBanner()
                : const SizedBox.shrink(),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 12, 12, 4),
            child: Obx(
              () => IgnorePointer(
                ignoring: ctrl.isCreating.value,
                child: NewChatTile(onTap: () => _createNewChat(context, ctrl)),
              ),
            ),
          ),
          Expanded(child: _buildListBody(context, ctrl)),
        ],
      ),
    );
  }

  Widget _buildWide(BuildContext context, HomeController ctrl) {
    return Scaffold(
      body: Row(
        children: [
          Container(
            width: 320,
            color: AppColors.surface,
            child: SafeArea(
              child: Column(
                children: [
                  Padding(
                    padding: const EdgeInsets.fromLTRB(20, 12, 16, 16),
                    child: Row(
                      children: [
                        Icon(
                          Icons.auto_awesome,
                          color: AppColors.accentGreen,
                          size: 20,
                        ),
                        const SizedBox(width: 10),
                        Text(
                          'My Documents',
                          style: Theme.of(context).textTheme.titleMedium,
                        ),
                        const Spacer(),
                        Obx(
                          () => IconButton(
                            icon: Icon(
                              Icons.refresh,
                              color: AppColors.textMuted,
                              size: 19,
                            ),
                            onPressed: ctrl.isLoading.value
                                ? null
                                : ctrl.loadChats,
                          ),
                        ),
                      ],
                    ),
                  ),
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 16),
                    child: SizedBox(
                      width: double.infinity,
                      child: Obx(
                        () => ElevatedButton.icon(
                          onPressed: ctrl.isCreating.value
                              ? null
                              : () => _createNewChat(context, ctrl),
                          icon: const Icon(Icons.add, size: 18),
                          label: const Text('New document'),
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(height: 12),
                  const Divider(height: 1),
                  Obx(
                    () => ctrl.isOffline.value
                        ? const OfflineBanner()
                        : const SizedBox.shrink(),
                  ),
                  Expanded(child: _buildListBody(context, ctrl)),
                  const UserProfileTile(),
                ],
              ),
            ),
          ),
          Expanded(
            child: Obx(() {
              final selected = ctrl.chats
                  .where((c) => c.id == ctrl.selectedChatId.value)
                  .toList();
              if (selected.isEmpty) {
                return EmptyState(
                  icon: Icons.chat_bubble_outline,
                  title: ctrl.chats.isEmpty
                      ? 'No documents yet'
                      : 'Select a document',
                  subtitle: ctrl.chats.isEmpty
                      ? 'Upload a PDF to start asking questions and get answers grounded in its actual pages.'
                      : 'Choose a conversation from the left, or start a new one.',
                  actionLabel: ctrl.chats.isEmpty ? 'New document' : null,
                  onAction: ctrl.chats.isEmpty
                      ? () => _createNewChat(context, ctrl)
                      : null,
                );
              }
              final chat = selected.first;
              return ChatScreen(
                key: ValueKey(chat.id),
                chatId: chat.id,
                title: chat.title,
                embedded: true,
              );
            }),
          ),
        ],
      ),
    );
  }

  Widget _buildListBody(BuildContext context, HomeController ctrl) {
    return Obx(() {
      if (ctrl.isLoading.value && ctrl.chats.isEmpty) {
        return Center(
          child: CircularProgressIndicator(color: AppColors.accentGreen),
        );
      }
      if (ctrl.errorMessage.value != null && ctrl.chats.isEmpty) {
        return Padding(
          padding: const EdgeInsets.all(24),
          child: EmptyState(
            icon: Icons.cloud_off_outlined,
            title: "Can't reach the server",
            subtitle: ctrl.errorMessage.value!,
            actionLabel: 'Retry',
            onAction: ctrl.loadChats,
          ),
        );
      }
      if (ctrl.isCreating.value) {
        return Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              CircularProgressIndicator(color: AppColors.accentGreen),
              SizedBox(height: 14),
              Text(
                'Uploading & processing…',
                style: TextStyle(color: AppColors.textMuted, fontSize: 13),
              ),
            ],
          ),
        );
      }
      if (ctrl.chats.isEmpty) {
        return Padding(
          padding: const EdgeInsets.all(24),
          child: EmptyState(
            icon: Icons.upload_file_outlined,
            title: 'No documents yet',
            subtitle: 'Upload a PDF to start a grounded, page-cited conversation with it.',
            actionLabel: 'New document',
            onAction: () => _createNewChat(context, ctrl),
          ),
        );
      }
      return ListView.separated(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
        itemCount: ctrl.chats.length,
        separatorBuilder: (_, __) => const SizedBox(height: 2),
        itemBuilder: (context, index) {
          final chat = ctrl.chats[index];
          return Obx(
            () => ChatListTile(
              chat: chat,
              selected: chat.id == ctrl.selectedChatId.value,
              onTap: () {
                if (isWide(context)) {
                  ctrl.selectChat(chat.id);
                } else {
                  Get.to(() => ChatScreen(chatId: chat.id, title: chat.title));
                }
              },
              onDelete: () => _deleteChat(context, ctrl, chat),
            ),
          );
        },
      );
    });
  }
}

/// Small avatar in the AppBar with a "Sign out" menu — the narrow home
/// screen has no drawer of its own (it IS the list), so this is where
/// account actions live for that layout.
class _AvatarMenuButton extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    final auth = Get.find<AuthController>();
    Future<void> _confirmSignOut(
      BuildContext context,
      AuthController auth,
    ) async {
      final confirmed = await showDialog<bool>(
        context: context,
        builder: (_) => AlertDialog(
          backgroundColor: AppColors.surface,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(16),
          ),
          title: const Text('Sign out?'),
          content: const Text(
            "You'll need to sign in again to see your documents.",
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('Cancel'),
            ),
            TextButton(
              onPressed: () => Navigator.pop(context, true),
              child: Text(
                'Sign out',
                style: TextStyle(color: AppColors.dangerRed),
              ),
            ),
          ],
        ),
      );
      if (confirmed == true) await auth.signOut();
    }

    return Obx(() {
      final user = auth.currentUser.value;
      if (user == null) return const SizedBox.shrink();
      return PopupMenuButton<String>(
        tooltip: 'Account',
        onSelected: (value) async {
          if (value == 'sign_out') await _confirmSignOut(context, auth);
        },
        itemBuilder: (context) => [
          PopupMenuItem(
            enabled: false,
            child: Text(user.email, style: const TextStyle(fontSize: 12)),
          ),
          const PopupMenuDivider(),
          const PopupMenuItem(value: 'sign_out', child: Text('Sign out')),
        ],
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 8),
          child: CircleAvatar(
            radius: 14,
            backgroundColor: AppColors.surfaceAlt,
            backgroundImage: user.pictureUrl != null
                ? NetworkImage(user.pictureUrl!)
                : null,
            child: user.pictureUrl == null
                ? Text(
                    user.initial,
                    style: TextStyle(
                      color: AppColors.accentGreen,
                      fontSize: 12,
                      fontWeight: FontWeight.bold,
                    ),
                  )
                : null,
          ),
        ),
      );
    });
  }
}
