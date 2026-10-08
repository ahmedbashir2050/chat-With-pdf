import 'dart:developer';

import 'package:chat_with_pdf/widgets/code_block_builder.dart';
import 'package:chat_with_pdf/widgets/math_text.dart';
import 'package:flutter/material.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';

class AIChatBubble extends StatelessWidget {
  const AIChatBubble({
    super.key,
    required this.text,
    required this.iscontainsArabic,
  });

  final String text;
  final bool iscontainsArabic;

  @override
  Widget build(BuildContext context) {
    // 🔥 IMPORTANT: streaming OR final BOTH use same widget
    log("AIChatBubble $text");
    return Directionality(
      textDirection: iscontainsArabic ? TextDirection.rtl : TextDirection.ltr,
      child: MarkdownBody(
        data: text,
        selectable: true,
        // inlineSyntaxes: [PageReferenceSyntax()],

        builders: {
          // 'page_ref': PageReferenceBuilder(),
          'code': CodeBlockBuilder(),
          'p': MathBuilder(),
        },
        styleSheet: MarkdownStyleSheet(
          p: const TextStyle(height: 1.8),

          h1: const TextStyle(fontSize: 26, fontWeight: FontWeight.bold),
          h2: const TextStyle(fontSize: 22, fontWeight: FontWeight.bold),
          h3: const TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
          code: const TextStyle(
            color: Colors.greenAccent,
            fontFamily: "monospace",
          ),
        ),
      ),
    );
  }
}
