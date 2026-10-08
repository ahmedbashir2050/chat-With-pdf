import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:get/get.dart';

import '../controllers/chat_controller.dart';
import '../theme/app_theme.dart';
import '../widgets/app_drawer.dart';
import '../widgets/chat_bubble.dart';
import '../widgets/empty_state.dart';
import '../widgets/offline_banner.dart';
import '../widgets/responsive.dart';
import '../widgets/upload_progress_dialog.dart';

class ChatScreen extends StatelessWidget {
  final int chatId;
  final String title;
  final bool embedded;

  const ChatScreen({
    super.key,
    required this.chatId,
    required this.title,
    this.embedded = false,
  });

  ChatController _controller() {
    final tag = chatId.toString();
    if (!Get.isRegistered<ChatController>(tag: tag)) {
      Get.put(ChatController(chatId: chatId), tag: tag);
    }
    return Get.find<ChatController>(tag: tag);
  }

  Future<void> _replacePDFresource(BuildContext context, ctrl) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        backgroundColor: AppColors.surface,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: const Text('Replace PDF resource?'),
        content: const Text(
          "This will replace the current PDF resource with a new one. Are you sure you want to proceed?",
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            child: Text(
              'Replace',
              style: TextStyle(color: AppColors.dangerRed),
            ),
          ),
        ],
      ),
    );
    if (confirmed == true) _replaceResource(context, ctrl);
  }

  @override
  Widget build(BuildContext context) {
    final ctrl = _controller();
    final wide = isWide(context);
    final bubbleMaxWidth = wide
        ? 620.0
        : MediaQuery.sizeOf(context).width * 0.78;

    return Scaffold(
      drawer: (embedded || wide) ? null : AppDrawer(currentChatId: chatId),
      appBar: AppBar(
        automaticallyImplyLeading: false,
        leading: (embedded || wide)
            ? null
            : Builder(
                builder: (ctx) => IconButton(
                  icon: const Icon(Icons.menu),
                  onPressed: () => Scaffold.of(ctx).openDrawer(),
                  tooltip: 'Chats',
                ),
              ),
        title: Text(title, style: const TextStyle(fontSize: 17)),
        actions: [
          IconButton(
            icon: const Icon(Icons.sync, size: 20),
            tooltip: 'Replace PDF resource',
            onPressed: () => _replacePDFresource(context, ctrl),
          ),
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
          Expanded(
            child: Obx(() {
              if (ctrl.isLoadingHistory.value && ctrl.messages.isEmpty) {
                return Center(
                  child: CircularProgressIndicator(
                    color: AppColors.accentGreen,
                  ),
                );
              }
              if (ctrl.messages.isEmpty) {
                return const EmptyState(
                  icon: Icons.forum_outlined,
                  title: 'Ask about this document',
                  subtitle: 'Try a specific question, or ask for a summary of a chapter or page range.',
                );
              }
              return Center(
                child: ConstrainedBox(
                  constraints: BoxConstraints(
                    maxWidth: wide ? 800 : double.infinity,
                  ),
                  child: ListView.builder(
                    controller: ctrl.scrollController,
                    padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
                    itemCount:
                        ctrl.messages.length + (ctrl.isSending.value ? 1 : 0),
                    itemBuilder: (context, index) {
                      if (index == ctrl.messages.length) {
                        return const Padding(
                          padding: EdgeInsets.only(bottom: 12),
                          child: Align(
                            alignment: Alignment.centerLeft,
                            child: ThinkingDots(),
                          ),
                        );
                      }
                      return ChatMessageTile(
                        message: ctrl.messages[index],
                        maxWidth: bubbleMaxWidth,
                      );
                    },
                  ),
                ),
              );
            }),
          ),
          _Composer(ctrl: ctrl, wide: wide),
        ],
      ),
    );
  }

  Future<void> _replaceResource(
    BuildContext context,
    ChatController ctrl,
  ) async {
    final result = await FilePicker.pickFiles(
      type: FileType.custom,
      allowedExtensions: ['pdf'],
      withData: true,
    );
    if (result == null || result.files.single.bytes == null) return;

    if (!context.mounted) return;
    final dialogFuture = UploadProgressDialog.show(
      context,
      ctrl.uploadProgress,
      label: 'Uploading updated PDF',
    );

    try {
      await ctrl.replaceResource(
        result.files.single.bytes!,
        result.files.single.name,
      );
      if (context.mounted) Navigator.of(context, rootNavigator: true).pop();
    } catch (e) {
      if (context.mounted) Navigator.of(context, rootNavigator: true).pop();
      Get.snackbar('Update failed', '$e');
    }
    await dialogFuture;
  }
}

// ─── Composer: text input + send button ───────────────────────────────────

class _Composer extends StatelessWidget {
  final ChatController ctrl;
  final bool wide;
  const _Composer({required this.ctrl, required this.wide});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(16, 10, 16, 14),
      decoration: BoxDecoration(
        color: AppColors.surface,
        border: Border(top: BorderSide(color: AppColors.border)),
      ),
      child: SafeArea(
        top: false,
        child: Center(
          child: ConstrainedBox(
            constraints: BoxConstraints(maxWidth: wide ? 800 : double.infinity),
            child: _idleBar(context),
          ),
        ),
      ),
    );
  }

  Widget _idleBar(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6),
      decoration: BoxDecoration(
        color: AppColors.surfaceAlt,
        borderRadius: BorderRadius.circular(28),
        border: Border.all(color: AppColors.border),
      ),
      child: Row(
        children: [
          Expanded(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 10),
              child: Obx(
                () => TextField(
                  controller: ctrl.inputController,
                  minLines: 1,
                  maxLines: 5,
                  enabled: !ctrl.isOffline.value,
                  textInputAction: TextInputAction.send,
                  decoration: InputDecoration(
                    hintText: ctrl.isOffline.value
                        ? 'Connect to ask a question…'
                        : 'Ask about this document…',
                  ),
                  onSubmitted: (_) => ctrl.sendQuestion(),
                ),
              ),
            ),
          ),
          const SizedBox(width: 6),
          Obx(
            () => _CircleBtn(
              icon: Icons.arrow_upward,
              color: AppColors.accentGreen,
              onTap: ctrl.isOffline.value ? null : ctrl.sendQuestion,
              size: 44,
            ),
          ),
          const SizedBox(width: 4),
        ],
      ),
    );
  }
}

/// Bordered circle button — tinted background, colored border, colored
/// icon — matching the reference app's send button style.
class _CircleBtn extends StatelessWidget {
  final IconData icon;
  final Color color;
  final VoidCallback? onTap;
  final double size;

  const _CircleBtn({
    required this.icon,
    required this.color,
    required this.onTap,
    required this.size,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      color: color.withOpacity(0.12),
      shape: CircleBorder(side: BorderSide(color: color.withOpacity(0.4))),
      child: InkWell(
        customBorder: const CircleBorder(),
        onTap: onTap,
        child: SizedBox(
          width: size,
          height: size,
          child: Icon(icon, color: color, size: size * 0.42),
        ),
      ),
    );
  }
}
