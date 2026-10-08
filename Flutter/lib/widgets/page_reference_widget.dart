import 'package:chat_with_pdf/theme/app_theme.dart';
import 'package:flutter/material.dart';

class PageReferenceWidget extends StatelessWidget {
  final String text;
  final bool isRtl;
  const PageReferenceWidget({
    super.key,
    required this.text,
    required this.isRtl,
  });

  List<String> _extractPages() {
    final pages = RegExp(r'\[p\.\s*([0-9٠-٩]+)\]')
        .allMatches(text)
        .map((match) => match.group(1)!)
        .toSet()
        .toList();

    return pages;
  }

  @override
  Widget build(BuildContext context) {
    final pages = _extractPages();
    final pageText = pages.join(' , ');

    return pageText.isEmpty
        ? SizedBox.shrink()
        : Row(
            mainAxisAlignment: isRtl
                ? MainAxisAlignment.end
                : MainAxisAlignment.start,
            children: [
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 2, vertical: 4),
                child: Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 8,
                    vertical: 4,
                  ),
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(16),
                    border: Border.all(color: Colors.grey, width: 0.1),
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(
                        Icons.menu_book,
                        size: 10,
                        color: AppColors.accentGreen,
                      ),
                      const SizedBox(width: 4),
                      Text(
                        'الصفحة : $pageText',
                        style: const TextStyle(fontSize: 8),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          );
  }
}
