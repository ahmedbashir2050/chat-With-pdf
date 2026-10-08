import 'package:flutter/material.dart';
import 'package:get/get.dart';

import '../theme/app_theme.dart';

/// A non-dismissible modal showing real upload percentage, driven by an
/// Rx<double> (0.0–1.0) that the caller updates from Dio's onSendProgress.
/// Call [show] before starting the upload and [Get.back] (or let [show]'s
/// future resolve once you pop it yourself) when it's done.
class UploadProgressDialog extends StatelessWidget {
  final RxDouble progress;
  final String label;

  const UploadProgressDialog({super.key, required this.progress, this.label = 'Uploading document'});

  static Future<void> show(BuildContext context, RxDouble progress, {String label = 'Uploading document'}) {
    return showDialog(
      context: context,
      barrierDismissible: false,
      builder: (_) => UploadProgressDialog(progress: progress, label: label),
    );
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: false,
      child: Dialog(
        backgroundColor: AppColors.surface,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
        child: Padding(
          padding: const EdgeInsets.all(28),
          child: Obx(() {
            final pct = (progress.value * 100).clamp(0, 100).round();
            final done = progress.value >= 1.0;
            return Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                SizedBox(
                  width: 72,
                  height: 72,
                  child: Stack(
                    alignment: Alignment.center,
                    children: [
                      SizedBox(
                        width: 72,
                        height: 72,
                        child: CircularProgressIndicator(
                          value: progress.value,
                          strokeWidth: 5,
                          backgroundColor: AppColors.surfaceAlt,
                          valueColor: AlwaysStoppedAnimation(AppColors.accentGreen),
                        ),
                      ),
                      done
                          ? Icon(Icons.check, color: AppColors.accentGreen, size: 26)
                          : Text('$pct%',
                              style: TextStyle(
                                  color: AppColors.textPrimary, fontWeight: FontWeight.w700, fontSize: 15)),
                    ],
                  ),
                ),
                const SizedBox(height: 18),
                Text(
                  done ? 'Processing…' : label,
                  style: TextStyle(color: AppColors.textPrimary, fontWeight: FontWeight.w600, fontSize: 14.5),
                ),
                const SizedBox(height: 6),
                Text(
                  done
                      ? 'Extracting text and generating embeddings — almost there.'
                      : 'Uploading $pct% complete…',
                  textAlign: TextAlign.center,
                  style: TextStyle(color: AppColors.textMuted, fontSize: 12.5),
                ),
              ],
            );
          }),
        ),
      ),
    );
  }
}
