import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

class AppColors {
  AppColors._();

  static const Color _accent = Color(0xFF10A37F);

  static late Color bg;
  static late Color surface;
  static late Color surfaceAlt;
  static late Color border;

  static late Color textPrimary;
  static late Color textMuted;
  static late Color textFaint;

  static late Color accentGreen;
  static late Color userBubble;
  static late Color warnAmber;
  static late Color dangerRed;
  static late Color dangerRedDeep;

  static void applyPalette({required bool isDark}) {
    if (isDark) {
      // DARK MODE
      bg = const Color(0xFF212121);
      surface = const Color(0xFF171717);
      surfaceAlt = const Color(0xFF2F2F2F);
      border = const Color(0xFF3A3A3A);

      textPrimary = const Color(0xFFECECEC);
      textMuted = const Color(0xFFB4B4B4);
      textFaint = const Color(0xFF8E8E8E);

      userBubble = const Color(0xFF2F2F2F);

      warnAmber = const Color(0xFFD29922);
      dangerRed = const Color(0xFFF85149);
      dangerRedDeep = const Color(0xFFDA3633);
    } else {
      // LIGHT MODE
      bg = const Color(0xFFf6F6F6);
      surface = const Color(0xFFF9F9F9);
      // surfaceAlt = const Color(0xFFF4F4F4);
      surfaceAlt = Colors.white;
      border = const Color(0xFFE5E5E5);

      textPrimary = const Color(0xFF0D0D0D);
      textMuted = const Color(0xFF676767);
      textFaint = const Color(0xFF8E8E8E);

      // userBubble = const Color(0xFFF4F4F4);
      userBubble = const Color(0xFFE5E5E5);
      warnAmber = const Color(0xFFB86E00);
      dangerRed = const Color(0xFFD1242F);
      dangerRedDeep = const Color(0xFFA6141F);
    }

    accentGreen = _accent;
  }
}

class AppTheme {
  AppTheme._();

  static ThemeData build({required bool isDark}) {
    // Keep AppColors synchronized with this ThemeData.
    AppColors.applyPalette(isDark: false);

    final onAccent = Colors.white;

    final base = ThemeData(
      useMaterial3: true,
      brightness: isDark ? Brightness.dark : Brightness.light,
      colorScheme:
          (isDark ? const ColorScheme.dark() : const ColorScheme.light())
              .copyWith(
                primary: AppColors.accentGreen,
                secondary: AppColors.accentGreen,
                surface: AppColors.surface,
                error: AppColors.dangerRed,
              ),
      scaffoldBackgroundColor: AppColors.bg,
    );

    final bodyFont = GoogleFonts.interTextTheme(base.textTheme).apply(
      bodyColor: AppColors.textPrimary,
      displayColor: AppColors.textPrimary,
    );

    return base.copyWith(
      textTheme: bodyFont.copyWith(
        headlineSmall: GoogleFonts.inter(
          fontSize: 20,
          fontWeight: FontWeight.w700,
          color: AppColors.textPrimary,
        ),
        titleLarge: GoogleFonts.inter(
          fontSize: 17,
          fontWeight: FontWeight.w700,
          color: AppColors.textPrimary,
        ),
        titleMedium: GoogleFonts.inter(
          fontSize: 15,
          fontWeight: FontWeight.w600,
          color: AppColors.textPrimary,
        ),
        bodyLarge: GoogleFonts.inter(
          fontSize: 15,
          height: 1.5,
          color: AppColors.textPrimary,
        ),
        bodyMedium: GoogleFonts.inter(
          fontSize: 14,
          height: 1.45,
          color: AppColors.textPrimary,
        ),
        bodySmall: GoogleFonts.inter(fontSize: 12, color: AppColors.textMuted),
        labelLarge: GoogleFonts.inter(
          fontWeight: FontWeight.w600,
          fontSize: 13.5,
        ),
      ),

      appBarTheme: AppBarTheme(
        backgroundColor: AppColors.bg,
        foregroundColor: AppColors.textPrimary,
        elevation: 0,
        surfaceTintColor: Colors.transparent,
        centerTitle: false,
        titleTextStyle: GoogleFonts.inter(
          fontSize: 17,
          fontWeight: FontWeight.w700,
          color: AppColors.textPrimary,
        ),
        iconTheme: IconThemeData(color: AppColors.textMuted),
      ),

      cardTheme: CardThemeData(
        color: AppColors.surface,
        elevation: 0,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(14),
          side: BorderSide(color: AppColors.border),
        ),
        margin: EdgeInsets.zero,
      ),

      inputDecorationTheme: InputDecorationTheme(
        filled: false,
        hintStyle: GoogleFonts.inter(
          color: AppColors.textFaint,
          fontSize: 14.5,
        ),
        border: InputBorder.none,
        enabledBorder: InputBorder.none,
        disabledBorder: InputBorder.none,
        focusedBorder: InputBorder.none,
        contentPadding: const EdgeInsets.symmetric(horizontal: 4, vertical: 12),
      ),

      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: AppColors.accentGreen,
          foregroundColor: onAccent,
          elevation: 0,
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(14),
          ),
          textStyle: GoogleFonts.inter(
            fontWeight: FontWeight.w600,
            fontSize: 14.5,
          ),
        ),
      ),

      floatingActionButtonTheme: FloatingActionButtonThemeData(
        backgroundColor: AppColors.accentGreen,
        foregroundColor: onAccent,
        elevation: 2,
      ),

      dividerTheme: DividerThemeData(color: AppColors.border, thickness: 1),

      snackBarTheme: SnackBarThemeData(
        backgroundColor: AppColors.surfaceAlt,
        contentTextStyle: GoogleFonts.inter(
          color: AppColors.textPrimary,
          fontSize: 13.5,
        ),
        behavior: SnackBarBehavior.floating,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      ),
    );
  }

  static TextStyle get citationMono => GoogleFonts.jetBrainsMono(
    fontSize: 11,
    fontWeight: FontWeight.w600,
    color: AppColors.accentGreen,
  );
}
