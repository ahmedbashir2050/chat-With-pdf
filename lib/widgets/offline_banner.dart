import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

class OfflineBanner extends StatelessWidget {
  const OfflineBanner({super.key});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      color: AppColors.surface,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      child: Row(
        children: [
          Icon(Icons.wifi_off, color: AppColors.warnAmber, size: 14),
          SizedBox(width: 8),
          Text('Offline — showing saved messages',
              style: TextStyle(color: AppColors.warnAmber, fontSize: 12)),
        ],
      ),
    );
  }
}
