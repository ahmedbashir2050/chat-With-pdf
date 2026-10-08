import 'dart:developer';

import 'package:chat_with_pdf/widgets/ai_chat_bubble.dart';
import 'package:chat_with_pdf/widgets/page_reference_widget.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../models/message.dart';
import '../theme/app_theme.dart';

/// One entry in the conversation. User messages render as a right-aligned
/// blue bubble (with a small mic badge if it came from voice); assistant
/// messages render left-aligned with a labeled header, citation-aware body,
/// and a small action row (copy + timestamp) — mirrors the reference UI.
class ChatMessageTile extends StatelessWidget {
  final ChatMessageModel message;
  final double maxWidth;

  const ChatMessageTile({
    super.key,
    required this.message,
    required this.maxWidth,
  });

  bool get _isUser => message.role == 'user';

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (_isUser)
            _buildUserBubble(context)
          else
            _buildAssistantContent(context),
        ],
      ),
    );
  }

  Widget _buildUserBubble(BuildContext context) {
    return Align(
      alignment: Alignment.centerRight,
      child: GestureDetector(
        onLongPress: () {
          Clipboard.setData(ClipboardData(text: message.content));
          // ScaffoldMessenger.of(context).showSnackBar(
          //   const SnackBar(content: Text('Message copied to clipboard')),
          // );
        },
        child: Container(
          constraints: BoxConstraints(maxWidth: maxWidth),
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
          decoration: BoxDecoration(
            color: AppColors.userBubble,
            borderRadius: BorderRadius.only(
              topLeft: Radius.circular(16),
              topRight: Radius.circular(4),
              bottomLeft: Radius.circular(16),
              bottomRight: Radius.circular(16),
            ),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              // if (message.isVoice) ...[
              //   Icon(Icons.mic, color: AppColors.textMuted, size: 13),
              //   const SizedBox(width: 4),
              // ],
              Flexible(
                child: Text(
                  message.content,
                  style: TextStyle(color: AppColors.textPrimary, fontSize: 14),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildAssistantContent(BuildContext context) {
    bool containsArabic(String text) {
      final arabicRegex = RegExp(r'[\u0600-\u06FF]');
      return arabicRegex.hasMatch(text);
    }

    final result = message.content
        .replaceAll(RegExp(r'\[p\.\s*[0-9٠-٩]+\]'), '')
        .replaceAll(RegExp(r' {2,}'), ' ')
        .trim();

    log('Original message: ${message.content}');
    log('removePageReferences: $result');
    log('isArabic: ${containsArabic(message.content)}');
    if (containsArabic(message.content)) {
      // log("Message content: ${message.content}");
      log("Arabic detected");
    } else {
      log("Not Arabic");
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Icon(Icons.auto_awesome, color: AppColors.accentGreen, size: 13),
            SizedBox(width: 4),
            Text(
              'Assistant',
              style: TextStyle(
                color: AppColors.accentGreen,
                fontSize: 11,
                fontWeight: FontWeight.bold,
              ),
            ),
          ],
        ),
        const SizedBox(height: 6),

        AIChatBubble(
          text: result,
          iscontainsArabic: containsArabic(message.content),
        ),
        PageReferenceWidget(
          text: message.content,
          isRtl: containsArabic(message.content),
        ),
        // ConstrainedBox(
        //   constraints: BoxConstraints(maxWidth: maxWidth),
        //   child: MessageBody(text: message.content, style: Theme.of(context).textTheme.bodyMedium),
        // ),
        const SizedBox(height: 6),
        Row(
          children: [
            Text(
              _fmtTime(message.createdAt),
              style: TextStyle(color: AppColors.textFaint, fontSize: 11),
            ),
            const SizedBox(width: 8),
            Material(
              color: Colors.transparent,
              child: InkWell(
                borderRadius: BorderRadius.circular(16),
                onTap: () =>
                    Clipboard.setData(ClipboardData(text: message.content)),
                child: Padding(
                  padding: EdgeInsets.all(3),
                  child: Icon(
                    Icons.copy_rounded,
                    size: 14,
                    color: AppColors.textFaint,
                  ),
                ),
              ),
            ),
          ],
        ),
      ],
    );
  }

  String _fmtTime(DateTime dt) {
    final now = DateTime.now();
    final diff = now.difference(dt);
    if (diff.inMinutes < 1) return 'just now';
    if (diff.inHours < 1) return '${diff.inMinutes}m ago';
    if (diff.inDays < 1) {
      return '${dt.hour.toString().padLeft(2, '0')}:${dt.minute.toString().padLeft(2, '0')}';
    }
    return '${dt.day}/${dt.month}/${dt.year}';
  }
}

/// Three pulsing dots shown while waiting for a reply.
class ThinkingDots extends StatefulWidget {
  const ThinkingDots({super.key});

  @override
  State<ThinkingDots> createState() => _ThinkingDotsState();
}

class _ThinkingDotsState extends State<ThinkingDots>
    with TickerProviderStateMixin {
  late final List<AnimationController> _controllers = List.generate(
    3,
    (i) => AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 600),
    )..repeat(reverse: true),
  );

  @override
  void dispose() {
    for (final c in _controllers) {
      c.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        color: AppColors.surface,
        border: Border.all(color: AppColors.border),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: List.generate(3, (i) {
          return Padding(
            padding: EdgeInsets.only(right: i < 2 ? 4 : 0),
            child: FadeTransition(
              opacity: Tween(begin: 0.2, end: 1.0).animate(_controllers[i]),
              child: Container(
                width: 7,
                height: 7,
                decoration: BoxDecoration(
                  color: AppColors.accentGreen,
                  shape: BoxShape.circle,
                ),
              ),
            ),
          );
        }),
      ),
    );
  }
}
