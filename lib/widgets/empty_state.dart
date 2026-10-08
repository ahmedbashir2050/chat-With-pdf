import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

class EmptyState extends StatelessWidget {
  final IconData icon;
  final String title;
  final String subtitle;
  final String? actionLabel;
  final VoidCallback? onAction;

  const EmptyState({
    super.key,
    required this.icon,
    required this.title,
    required this.subtitle,
    this.actionLabel,
    this.onAction,
  });

  @override
  Widget build(BuildContext context) {
    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 340),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 72,
              height: 72,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: AppColors.accentGreen.withOpacity(0.1),
                border: Border.all(color: AppColors.accentGreen.withOpacity(0.3)),
              ),
              child: Icon(icon, size: 30, color: AppColors.accentGreen),
            ),
            const SizedBox(height: 18),
            Text(title, style: Theme.of(context).textTheme.headlineSmall, textAlign: TextAlign.center),
            const SizedBox(height: 8),
            Text(
              subtitle,
              style: TextStyle(color: AppColors.textMuted, fontSize: 13),
              textAlign: TextAlign.center,
            ),
            if (actionLabel != null) ...[
              const SizedBox(height: 22),
              ElevatedButton.icon(
                onPressed: onAction,
                icon: const Icon(Icons.add, size: 18),
                label: Text(actionLabel!),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
