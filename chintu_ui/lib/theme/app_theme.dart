import 'package:flutter/material.dart';

class AppColors {
  static const Color background = Color(0xFF000000);
  static const Color surface = Color(0xFF080808);
  static const Color surfaceStrong = Color(0xFF101010);
  static const Color surfaceElevated = Color(0xFF161616);
  static const Color border = Color(0xFF1F1F1F);
  static const Color textPrimary = Color(0xFFFFFFFF);
  static const Color textMuted = Color(0xFF888888);
  // Backwards compatibility for older widgets that referenced "textSecondary"
  static const Color textSecondary = textMuted;
  static const Color accent = Color(0xFF00BFA5); // Modern Teal
  static const Color accentSoft = Color(0xFF64FFDA); // Light Teal
  static const Color accentDeep = Color(0xFF00796B); // Deep Teal
  static const Color success = Color(0xFF00BFA5);
  static const Color warning = Color(0xFFFFD600);
  static const Color danger = Color(0xFFFF1744);
}

class AppTheme {
  static const String fontBody = 'Sora';
  static const String fontDisplay = 'SpaceGrotesk';

  static ThemeData dark() {
    final colorScheme = const ColorScheme.dark(
      primary: AppColors.accent,
      secondary: AppColors.accentSoft,
      surface: AppColors.surface,
      error: AppColors.danger,
    );
    final base = ThemeData.from(colorScheme: colorScheme);
    final baseText = base.textTheme.apply(
      fontFamily: fontBody,
      bodyColor: AppColors.textPrimary,
      displayColor: AppColors.textPrimary,
    );
    return ThemeData(
      colorScheme: colorScheme,
      scaffoldBackgroundColor: AppColors.background,
      fontFamily: fontBody,
      cardColor: AppColors.surface,
      dividerColor: AppColors.border,
      splashColor: AppColors.accent.withValues(alpha: 0.08),
      textTheme: baseText.copyWith(
        displayLarge: const TextStyle(
          fontFamily: fontDisplay,
          fontSize: 40,
          fontWeight: FontWeight.w600,
          letterSpacing: 1.2,
          color: AppColors.textPrimary,
        ),
        headlineMedium: const TextStyle(
          fontFamily: fontDisplay,
          fontSize: 26,
          fontWeight: FontWeight.w700,
          letterSpacing: 0.8,
          color: AppColors.textPrimary,
        ),
        titleLarge: const TextStyle(
          fontFamily: fontDisplay,
          fontSize: 18,
          fontWeight: FontWeight.w600,
          letterSpacing: 0.4,
          color: AppColors.textPrimary,
        ),
        titleMedium: const TextStyle(
          fontFamily: fontDisplay,
          fontSize: 16,
          fontWeight: FontWeight.w600,
          letterSpacing: 0.3,
          color: AppColors.textPrimary,
        ),
        bodyLarge: const TextStyle(
          fontFamily: fontBody,
          fontSize: 16,
          fontWeight: FontWeight.w400,
          color: AppColors.textPrimary,
        ),
        bodyMedium: const TextStyle(
          fontFamily: fontBody,
          fontSize: 14,
          fontWeight: FontWeight.w400,
          color: AppColors.textPrimary,
        ),
        bodySmall: const TextStyle(
          fontFamily: fontBody,
          fontSize: 12,
          fontWeight: FontWeight.w400,
          color: AppColors.textMuted,
        ),
        labelLarge: const TextStyle(
          fontFamily: fontBody,
          fontSize: 12,
          fontWeight: FontWeight.w600,
          letterSpacing: 0.6,
          color: AppColors.textMuted,
        ),
      ),
      iconTheme: const IconThemeData(color: AppColors.textPrimary),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: AppColors.surfaceStrong.withValues(alpha: 0.7),
        labelStyle: TextStyle(color: AppColors.textMuted),
        hintStyle: TextStyle(color: AppColors.textMuted.withValues(alpha: 0.7)),
        enabledBorder: OutlineInputBorder(
          borderSide: BorderSide(color: AppColors.border.withValues(alpha: 0.6)),
          borderRadius: BorderRadius.circular(12),
        ),
        focusedBorder: OutlineInputBorder(
          borderSide: const BorderSide(color: AppColors.accent, width: 1.2),
          borderRadius: BorderRadius.circular(12),
        ),
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: AppColors.accent,
          foregroundColor: Colors.white,
          padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 18),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: AppColors.textPrimary,
          side: BorderSide(color: AppColors.border.withValues(alpha: 0.7)),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
        ),
      ),
    );
  }

  static const LinearGradient appBackground = LinearGradient(
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
    colors: [
      Color(0xFF000000),
      Color(0xFF050505),
      Color(0xFF000000),
    ],
  );
}
