import 'package:flutter/material.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';
import 'package:flutter/services.dart';

class CodeBlockBuilder extends MarkdownElementBuilder {
  @override
  Widget visitElementAfter(element, TextStyle? preferredStyle) {
    final code = element.textContent;

    return Container(
      margin: const EdgeInsets.symmetric(vertical: 8),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: const Color(0xFF0D0D0D),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Stack(
        children: [
          SelectableText(
            " \n\n $code",
            style: const TextStyle(
              color: Colors.greenAccent,
              fontFamily: "monospace",
            ),
          ),
          Positioned(
            right: 0,
            child: IconButton(
              icon: const Icon(Icons.copy, size: 18, color: Colors.white54),
              onPressed: () {
                Clipboard.setData(ClipboardData(text: code));
              },
            ),
          ),
        ],
      ),
    );
  }
}
