import 'dart:convert';

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:google_sign_in/google_sign_in.dart';
import 'package:http/http.dart' as http;

import '../config.dart';
import '../models/app_user.dart';

/// Handles the Google Sign-In flow, exchanges the Google ID token for our
/// own backend session token, and persists that session in secure storage
/// (iOS Keychain / Android Keystore — never plain SharedPreferences/Hive,
/// since this is a credential, not app data).
///
/// Written against google_sign_in ^7.2.0, which replaced the old
/// `GoogleSignIn()` constructor + imperative `signIn()`/`signInSilently()`
/// with a single `GoogleSignIn.instance` that must be explicitly
/// `initialize()`d once, plus `authenticate()` (interactive) and
/// `attemptLightweightAuthentication()` (silent) in its place. See
/// `init()` and `signInWithGoogle()` below for exactly what changed and
/// why, and the module-level NOTE further down about Web specifically.
class AuthService {
  AuthService._();

  // The "Web application" OAuth client ID from Google Cloud Console.
  // Required so Google issues an ID token whose audience the FastAPI
  // backend can verify — see the setup notes shipped alongside this
  // project. This is a public client identifier, not a secret; it is
  // safe to ship in the compiled app on every platform.
  static const String _webClientId =
      '465983277425-f1elap5bhuho4qeruatvfvj9v33bre6g.apps.googleusercontent.com';

  static final GoogleSignIn _googleSignIn = GoogleSignIn.instance;

  static const _storage = FlutterSecureStorage();
  static const _tokenKey = 'session_token';
  static const _userKey = 'session_user';

  /// Cached in memory after the first read so ApiService can attach the
  /// Authorization header synchronously on every request without an async
  /// storage round-trip per call.
  static String? _cachedToken;

  static String? get currentToken => _cachedToken;

  /// `GoogleSignIn.instance` must be initialized exactly once before any
  /// other call (`authenticate()`, `attemptLightweightAuthentication()`,
  /// etc.) — this is new in v7; the old `GoogleSignIn(...)` constructor
  /// used to do this implicitly. Call this once at app startup (see
  /// main.dart) before AuthGate ever tries to restore or start a session.
  ///
  /// Platform split, and why:
  /// - `serverClientId` (Android/iOS): makes Google mint an ID token whose
  ///   *audience* is our backend's web OAuth client, so the FastAPI
  ///   backend can verify it — this preserves the exact same backend
  ///   contract the v6 implementation relied on via its own
  ///   `serverClientId` constructor argument.
  /// - `clientId` (Web): on Web, Google Identity Services needs the
  ///   platform's own client id up front to initialize the JS SDK;
  ///   passing `serverClientId` instead is not the correct parameter for
  ///   that purpose on this platform. Android/iOS don't need `clientId`
  ///   passed explicitly here — it's read from the native project
  ///   configuration (`google-services.json` / `GoogleService-Info.plist`)
  ///   the same way it always was.
  static Future<void> init() {
    return _googleSignIn.initialize(
      clientId: kIsWeb ? _webClientId : null,
      serverClientId: kIsWeb ? null : _webClientId,
    );
  }

  /// Called once at app startup to restore a previous *backend* session,
  /// if any. Note this restores our own session token from secure
  /// storage — it does not depend on Google's SDK at all, so it's
  /// unaffected by the google_sign_in version.
  static Future<AppUser?> restoreSession() async {
    final token = await _storage.read(key: _tokenKey);
    final userJson = await _storage.read(key: _userKey);
    if (token == null || userJson == null) return null;
    _cachedToken = token;
    return AppUser.fromJson(jsonDecode(userJson));
  }

  /// Runs the full flow: Google account picker → Google ID token → backend
  /// verifies it and returns our own session token + user profile.
  ///
  /// NOTE on Web: google_sign_in's `authenticate()` is an explicit,
  /// imperative "pop the account picker right now" call. This is fully
  /// supported on Android/iOS. On Web, Google Identity Services requires
  /// the sign-in gesture to originate from a button Google itself
  /// renders (a browser/GIS security requirement, not a Flutter
  /// limitation) — `supportsAuthenticate()` reports this per platform so
  /// we never call an unsupported method rather than guessing from
  /// `kIsWeb` alone. Where it's unsupported, we fall back to
  /// `attemptLightweightAuthentication()` (silent-only; no popup) and
  /// surface a clear error asking the user to use the Google-rendered
  /// button if that doesn't succeed. I could not verify against the live
  /// package docs in this environment whether the specific
  /// `google_sign_in_web` release paired with core 7.2.0 has changed
  /// this — see the final report's "flag for verification" note.
  static Future<AppUser> signInWithGoogle() async {
    await init();

    GoogleSignInAccount googleUser;
    if (_googleSignIn.supportsAuthenticate()) {
      try {
        googleUser = await _googleSignIn.authenticate();
      } on GoogleSignInException catch (e) {
        if (e.code == GoogleSignInExceptionCode.canceled) {
          throw Exception('Sign-in cancelled.');
        }
        throw Exception('Google sign-in failed: ${e.description ?? e.code}');
      }
    } else {
      // Web (or any platform without an interactive `authenticate()`):
      // attempt a silent sign-in only. If the user isn't already
      // signed in to a Google session the browser can restore, this
      // returns null and the caller sees a clear, actionable error
      // rather than a silent hang.
      final restored = await _googleSignIn.attemptLightweightAuthentication();
      if (restored == null) {
        throw Exception(
          'Interactive Google sign-in on this platform requires the '
          'Google-rendered sign-in button; silent sign-in found no '
          'existing session.',
        );
      }
      googleUser = restored;
    }

    // v7: authentication data (including the ID token) is returned
    // synchronously alongside the account — no separate awaited
    // `.authentication` Future round trip like in v6.
    final idToken = googleUser.authentication.idToken;
    if (idToken == null) {
      throw Exception('Google did not return an ID token.');
    }

    final response = await http.post(
      Uri.parse('$kApiBaseUrl/auth/google'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'id_token': idToken}),
    );

    if (response.statusCode != 200) {
      throw Exception('Sign-in failed: ${response.body}');
    }

    final data = jsonDecode(response.body);
    final token = data['access_token'] as String;
    final user = AppUser.fromJson(data['user']);

    _cachedToken = token;
    await _storage.write(key: _tokenKey, value: token);
    await _storage.write(key: _userKey, value: jsonEncode(user.toJson()));

    return user;
  }

  static Future<void> signOut() async {
    _cachedToken = null;
    await _storage.delete(key: _tokenKey);
    await _storage.delete(key: _userKey);
    try {
      await _googleSignIn.signOut();
    } catch (_) {
      // Not fatal — our own session is already cleared either way.
    }
  }
}
