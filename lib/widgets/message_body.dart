import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

/// Matches citation markers like "[p. 4]", "[p. 4-7]", "[p. 4, p. 9]".
final RegExp _citationPattern = RegExp(r'\[p\.\s?[\d,\-\s]+\]');

/// Renders message text with any "[p. X]" citations pulled out into small
/// bordered pill chips inline with the text, instead of raw bracket text —
/// same idea as the reference app's page-reference chips.
class MessageBody extends StatelessWidget {
  final String text;
  final TextStyle? style;

  const MessageBody({super.key, required this.text, this.style});

  @override
  Widget build(BuildContext context) {
    final baseStyle = style ?? Theme.of(context).textTheme.bodyMedium!;
    final spans = <InlineSpan>[];
    int lastEnd = 0;

    for (final match in _citationPattern.allMatches(text)) {
      if (match.start > lastEnd) {
        spans.add(TextSpan(text: text.substring(lastEnd, match.start), style: baseStyle));
      }
      final label = match.group(0)!.replaceAll(RegExp(r'[\[\]]'), '');
      spans.add(WidgetSpan(
        alignment: PlaceholderAlignment.middle,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 2),
          child: _CitationChip(label: label),
        ),
      ));
      lastEnd = match.end;
    }
    if (lastEnd < text.length) {
      spans.add(TextSpan(text: text.substring(lastEnd), style: baseStyle));
    }

    return Text.rich(TextSpan(children: spans), style: baseStyle);
  }
}

class _CitationChip extends StatelessWidget {
  final String label;
  const _CitationChip({required this.label});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: AppColors.accentGreen.withOpacity(0.35)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.menu_book, size: 10, color: AppColors.accentGreen),
          const SizedBox(width: 3),
          Text(label, style: AppTheme.citationMono),
        ],
      ),
    );
  }
}
