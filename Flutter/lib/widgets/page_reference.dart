import 'package:chat_with_pdf/theme/app_theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';
import 'package:markdown/markdown.dart' as md;

class PageReferenceBuilder extends MarkdownElementBuilder {
  @override
  Widget? visitElementAfter(md.Element element, TextStyle? preferredStyle) {
    final page = element.textContent;

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 2),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
        decoration: BoxDecoration(
          // color: Colors.blue.shade50,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: Colors.grey, width: 0.1),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.menu_book, size: 10, color: AppColors.accentGreen),
            const SizedBox(width: 4),
            Text(
              'الصفحة : $page',
              style: const TextStyle(
                fontSize: 8,
                // fontWeight: FontWeight.w600,
                // color: Colors.greenAccent,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
