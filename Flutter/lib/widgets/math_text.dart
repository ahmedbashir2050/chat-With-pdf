import 'package:flutter/material.dart';
import 'package:flutter_math_fork/flutter_math.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';

class MathBuilder extends MarkdownElementBuilder {
  @override
  Widget visitElementAfter(dynamic element, TextStyle? style) {
    final text = element.textContent;

    // block math
    if (text.startsWith('##') && text.endsWith('##')) {
      final formula = text.substring(2, text.length - 2);

      return SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: Math.tex(
          formula,
          textStyle: const TextStyle(color: Colors.black),
        ),
      );
    }

    // inline math
    if (text.contains(r'$')) {
      final formula = text.replaceAll(r'$', '');

      return Math.tex(formula, textStyle: const TextStyle(color: Colors.black));
    }

    return Text(text);
  }
}
