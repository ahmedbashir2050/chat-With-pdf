class ChatMessageModel {
  final int id;
  final String role; // 'user' | 'assistant'
  final String content;
  final DateTime createdAt;
  final bool isLoading;
  final bool isPending; // created locally while offline, not yet synced
  final double? confidenceScore; // 0.0-1.0; null for history messages (GET /messages doesn't return this)

  ChatMessageModel({
    required this.id,
    required this.role,
    required this.content,
    required this.createdAt,
    this.isLoading = false,
    this.isPending = false,
    this.confidenceScore,
  });

  factory ChatMessageModel.fromJson(Map<String, dynamic> json) =>
      ChatMessageModel(
        id: json['id'] as int,
        role: json['role'] as String,
        content: json['content'] as String,
        createdAt: DateTime.parse(json['created_at'] as String),
      );

  Map<String, dynamic> toJson() => {
    'id': id,
    'role': role,
    'content': content,
    'created_at': createdAt.toIso8601String(),
  };

  ChatMessageModel copyWith({
    String? content,
    bool? isLoading,
    bool? isPending,
  }) => ChatMessageModel(
    id: id,
    role: role,
    content: content ?? this.content,
    createdAt: createdAt,
    isLoading: isLoading ?? this.isLoading,
    isPending: isPending ?? this.isPending,
    confidenceScore: confidenceScore,
  );
}
