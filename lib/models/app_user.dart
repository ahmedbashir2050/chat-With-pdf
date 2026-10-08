class AppUser {
  final int id;
  final String email;
  final String? name;
  final String? pictureUrl;

  AppUser({required this.id, required this.email, this.name, this.pictureUrl});

  factory AppUser.fromJson(Map<String, dynamic> json) => AppUser(
        id: json['id'] as int,
        email: json['email'] as String,
        name: json['name'] as String?,
        pictureUrl: json['picture_url'] as String?,
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'email': email,
        'name': name,
        'picture_url': pictureUrl,
      };

  String get initial => (name?.isNotEmpty == true ? name![0] : email[0]).toUpperCase();
}
