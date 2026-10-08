class Chat {
  final int id;
  final String title;
  final String pdfName;
  final DateTime createdAt;
  final String overview;

  Chat({
    required this.id,
    required this.title,
    required this.pdfName,
    required this.createdAt,
    required this.overview,
  });

  factory Chat.fromJson(Map<String, dynamic> json) => Chat(
    id: json['id'] as int,
    title: json['title'] as String,
    pdfName: json['pdf_name'] as String,
    createdAt: DateTime.parse(json['created_at'] as String),
    overview: json['overview'] as String? ?? '',
  );

  Map<String, dynamic> toJson() => {
    'id': id,
    'title': title,
    'pdf_name': pdfName,
    'created_at': createdAt.toIso8601String(),
    'overview': overview,
  };
}
