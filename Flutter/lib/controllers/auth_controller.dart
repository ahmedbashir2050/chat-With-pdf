import 'package:chat_with_pdf/controllers/chat_controller.dart';
import 'package:chat_with_pdf/controllers/home_controller.dart';
import 'package:chat_with_pdf/services/auth_service.dart';
import 'package:get/get.dart';

import '../models/app_user.dart';

import '../services/local_store.dart';

class AuthController extends GetxController {
  final currentUser = Rxn<AppUser>();
  final isLoading =
      true.obs; // true while restoring a previous session at startup
  final isSigningIn = false.obs;
  final errorMessage = RxnString();

  bool get isLoggedIn => currentUser.value != null;

  @override
  void onInit() {
    super.onInit();
    _restoreSession();
  }

  Future<void> _restoreSession() async {
    isLoading.value = true;
    try {
      final user = await AuthService.restoreSession();
      currentUser.value = user;
      LocalStore.setCurrentUser(user?.id);
    } finally {
      isLoading.value = false;
    }
  }

  Future<void> signInWithGoogle() async {
    isSigningIn.value = true;
    errorMessage.value = null;
    try {
      final user = await AuthService.signInWithGoogle();
      currentUser.value = user;
      LocalStore.setCurrentUser(user.id);
    } catch (e) {
      errorMessage.value = '$e';
    } finally {
      isSigningIn.value = false;
    }
  }

  Future<void> signOut() async {
    await AuthService.signOut();
    await LocalStore.clearAll();
    LocalStore.setCurrentUser(null);
    currentUser.value = null;
    // Every GetX controller tagged to a chat (ChatController instances) or
    // the home list should not survive into the next session.
    Get.delete<ChatController>(force: true);
    Get.delete<HomeController>(force: true);
    // Get.deleteAll(force: true);
  }
}
