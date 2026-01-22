import 'package:flutter/material.dart';

class AppColors {
  static const Color background = Color(0xFF0B1020);
  static const Color surface = Color(0xFF121829);
  static const Color surfaceStrong = Color(0xFF1A2238);
  static const Color border = Color(0xFF24304A);
  static const Color textPrimary = Color(0xFFE6E9F2);
  static const Color textMuted = Color(0xFF9AA7BD);
  static const Color accent = Color(0xFF22D3EE);
  static const Color accentSoft = Color(0xFF7DD3FC);
  static const Color success = Color(0xFF22C55E);
  static const Color warning = Color(0xFFF59E0B);
  static const Color danger = Color(0xFFEF4444);
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
          fontWeight: FontWeight.w600,
          letterSpacing: 0.6,
          color: AppColors.textPrimary,
        ),
        titleLarge: const TextStyle(
          fontFamily: fontDisplay,
          fontSize: 18,
          fontWeight: FontWeight.w600,
          letterSpacing: 0.4,
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
    );
  }

  static const LinearGradient appBackground = LinearGradient(
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
    colors: [
      Color(0xFF0B1020),
      Color(0xFF10172B),
      Color(0xFF0B1020),
    ],
  );
}
