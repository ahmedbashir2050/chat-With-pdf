import 'dart:async';

import 'package:chat_with_pdf/services/auth_service.dart';
import 'package:flutter/material.dart';
import 'package:get/get.dart';

import 'controllers/auth_controller.dart';
import 'screens/home_screen.dart';
import 'screens/login_screen.dart';
// import 'services/auth_service.dart';
import 'services/local_store.dart';
import 'theme/app_theme.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await LocalStore.init();
  // Fire-and-forget: warms up GoogleSignIn.instance so the very first
  // "Sign in" tap doesn't wait on its setup latency. signInWithGoogle()
  // also awaits AuthService.init() itself, so correctness never depends
  // on this call finishing before app startup does — a failure here
  // (e.g. missing platform OAuth config) must not crash app boot.

  // await AuthService.init();
  // unawaited(AuthService.init().catchError((_) {}));
  // //
  // The app ships with a single fixed dark theme — no user-selectable
  // theming. AppColors.applyPalette must still run once before any widget
  // reads AppColors.* (e.g. AuthGate's loading Scaffold below).
  // AppColors.applyPalette(isDark: true);
  // final appTheme = AppTheme.build(isDark: true);
  runApp(MyApp());
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return GetMaterialApp(
      title: 'Chat with PDF',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.build(isDark: false),
      darkTheme: AppTheme.build(isDark: true),
      themeMode: ThemeMode.system,
      home: const AuthGate(),
    );
  }
}

/// Decides which screen to show based on session state: a brief splash
/// while restoring a previous session from secure storage, then either
/// the login screen or straight into the app.
class AuthGate extends StatelessWidget {
  const AuthGate({super.key});

  @override
  Widget build(BuildContext context) {
    final ctrl = Get.isRegistered<AuthController>()
        ? Get.find<AuthController>()
        : Get.put(AuthController());

    return Obx(() {
      if (ctrl.isLoading.value) {
        return Scaffold(
          backgroundColor: AppColors.bg,
          body: Center(
            child: CircularProgressIndicator(color: AppColors.accentGreen),
          ),
        );
      }

      return ctrl.isLoggedIn ? const HomeScreen() : const LoginScreen();
    });
  }
}
