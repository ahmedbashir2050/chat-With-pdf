// import 'package:markdown/markdown.dart' as md;

// class PageReferenceSyntax extends md.InlineSyntax {
//   PageReferenceSyntax() : super(r'\[p\.\s*([0-9٠-٩]+)\]');
//   // PageReferenceSyntax() : super(r'\[p\.\s*(\d+)\]');

//   @override
//   bool onMatch(md.InlineParser parser, Match match) {
//     print("Matched: ${match.group(0)}");
//     print("Page: ${match.group(1)}");

//     parser.addNode(md.Element.text('page_ref', match.group(1)!));
//     return true;
//   }
// }

import 'package:markdown/markdown.dart' as md;

class PageReferenceSyntax extends md.InlineSyntax {
  PageReferenceSyntax() : super(r'(?:(?:\[p\.\s*[0-9٠-٩]+\]))+');

  @override
  bool onMatch(md.InlineParser parser, Match match) {
    final text = match.group(0)!;

    final pages = RegExp(r'\[p\.\s*([0-9٠-٩]+)\]')
        .allMatches(text)
        .map((match) => match.group(1)!)
        .toList();

    parser.addNode(md.Element.text('page_ref', pages.join(' , ')));

    return true;
  }
}
