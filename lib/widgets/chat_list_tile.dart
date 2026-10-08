import 'package:flutter/material.dart';

import '../models/chat.dart';
import '../theme/app_theme.dart';

/// Pinned "start a new chat" entry — same role as the top item in
/// ChatGPT's sidebar/drawer. Shared between the home list and the drawer.
class NewChatTile extends StatelessWidget {
  final VoidCallback onTap;
  const NewChatTile({super.key, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return Material(
      color: AppColors.surfaceAlt,
      borderRadius: BorderRadius.circular(12),
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: onTap,
        child: Padding(
          padding: EdgeInsets.symmetric(horizontal: 14, vertical: 13),
          child: Row(
            children: [
              Icon(
                Icons.add_circle_outline,
                color: AppColors.accentGreen,
                size: 19,
              ),
              SizedBox(width: 12),
              Text(
                'New chat — add a PDF',
                style: TextStyle(
                  color: AppColors.textPrimary,
                  fontWeight: FontWeight.w600,
                  fontSize: 14,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class ChatListTile extends StatelessWidget {
  final Chat chat;
  final bool selected;
  final VoidCallback onTap;
  final VoidCallback? onDelete;

  const ChatListTile({
    super.key,
    required this.chat,
    required this.onTap,
    this.selected = false,
    this.onDelete,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      color: selected ? AppColors.surfaceAlt : Colors.transparent,
      borderRadius: BorderRadius.circular(12),
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: onTap,
        onLongPress: onDelete,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 11),
          child: Row(
            children: [
              Container(
                width: 34,
                height: 34,
                alignment: Alignment.center,
                decoration: BoxDecoration(
                  color: AppColors.surfaceAlt,
                  borderRadius: BorderRadius.circular(9),
                ),
                child: Icon(
                  Icons.description_outlined,
                  size: 16,
                  color: AppColors.accentGreen,
                ),
              ),
              const SizedBox(width: 11),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      chat.title,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        color: AppColors.textPrimary,
                        fontWeight: FontWeight.w600,
                        fontSize: 14,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      chat.pdfName,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        color: AppColors.textMuted,
                        fontSize: 12,
                      ),
                    ),
                  ],
                ),
              ),
              if (onDelete != null)
                IconButton(
                  icon: Icon(
                    Icons.delete_outline,
                    size: 18,
                    color: AppColors.textFaint,
                  ),
                  onPressed: onDelete,
                  tooltip: 'Delete',
                  visualDensity: VisualDensity.compact,
                ),
            ],
          ),
        ),
      ),
    );
  }
}
