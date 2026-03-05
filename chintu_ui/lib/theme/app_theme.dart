import 'package:flutter/material.dart';

class AppColors {
  static const Color background = Color(0xFF050505);
  static const Color surface = Color(0xFF0E0E0E);
  static const Color surfaceStrong = Color(0xFF151515);
  static const Color surfaceElevated = Color(0xFF1C1C1C);
  static const Color border = Color(0xFF2B2B2B);
  static const Color borderStrong = Color(0xFF3A3A3A);

  static const Color textPrimary = Color(0xFFF5F5F5);
  static const Color textMuted = Color(0xFF9A9A9A);

  // Backwards compatibility
  static const Color textSecondary = textMuted;

  // Minimal accent (teal)
  static const Color accent = Color(0xFF28CFC2);
  static const Color accentSoft = Color(0xFF72E4DB);
  static const Color accentDeep = Color(0xFF1FA89F);

  static const Color success = Color(0xFF35C38D);
  static const Color warning = Color(0xFFE8B95C);
  static const Color danger = Color(0xFFE26666);
}

class AppTheme {
  static const String fontBody = 'Sora';
  static const String fontDisplay = 'SpaceGrotesk';

  static ThemeData dark() {
    const colorScheme = ColorScheme.dark(
      primary: AppColors.accent,
      secondary: AppColors.accentSoft,
      surface: AppColors.surface,
      error: AppColors.danger,
      onPrimary: Colors.black,
      onSurface: AppColors.textPrimary,
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
      splashColor: AppColors.accent.withValues(alpha: 0.1),
      useMaterial3: true,

      // Text Theme
      textTheme: baseText.copyWith(
        displayLarge: const TextStyle(
          fontFamily: fontDisplay,
          fontSize: 34,
          fontWeight: FontWeight.w600,
          letterSpacing: 0.2,
          color: AppColors.textPrimary,
        ),
        headlineMedium: const TextStyle(
          fontFamily: fontDisplay,
          fontSize: 22,
          fontWeight: FontWeight.w600,
          letterSpacing: 0.1,
          color: AppColors.textPrimary,
        ),
        titleLarge: const TextStyle(
          fontFamily: fontDisplay,
          fontSize: 17,
          fontWeight: FontWeight.w600,
          letterSpacing: 0.1,
          color: AppColors.textPrimary,
        ),
        bodyLarge: const TextStyle(
          fontFamily: fontBody,
          fontSize: 16,
          fontWeight: FontWeight.w400,
          height: 1.5,
          color: AppColors.textPrimary,
        ),
        bodyMedium: const TextStyle(
          fontFamily: fontBody,
          fontSize: 14,
          fontWeight: FontWeight.w400,
          height: 1.4,
          color: AppColors.textPrimary,
        ),
      ),

      // Icon Theme
      iconTheme: const IconThemeData(color: AppColors.textMuted),

      // Input Decoration
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: AppColors.surfaceElevated,
        labelStyle: const TextStyle(color: AppColors.textMuted),
        hintStyle: TextStyle(color: AppColors.textMuted.withValues(alpha: 0.5)),
        contentPadding: const EdgeInsets.symmetric(
          horizontal: 16,
          vertical: 14,
        ),
        enabledBorder: OutlineInputBorder(
          borderSide: const BorderSide(color: AppColors.border, width: 1),
          borderRadius: BorderRadius.circular(12),
        ),
        focusedBorder: OutlineInputBorder(
          borderSide: const BorderSide(color: AppColors.accent, width: 1.2),
          borderRadius: BorderRadius.circular(12),
        ),
        errorBorder: OutlineInputBorder(
          borderSide: const BorderSide(color: AppColors.danger),
          borderRadius: BorderRadius.circular(12),
        ),
      ),

      // Button Themes
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: AppColors.accent,
          foregroundColor: Colors.black,
          padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 20),
          elevation: 0,
          textStyle: const TextStyle(
            fontWeight: FontWeight.w600,
            fontSize: 13.5,
          ),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(10),
          ),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: AppColors.textPrimary,
          side: const BorderSide(color: AppColors.borderStrong),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(10),
          ),
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(foregroundColor: AppColors.textMuted),
      ),
      appBarTheme: const AppBarTheme(
        backgroundColor: Colors.transparent,
        elevation: 0,
        foregroundColor: AppColors.textPrimary,
      ),
    );
  }

  static const Gradient appBackground = RadialGradient(
    center: Alignment.topCenter,
    radius: 1.8,
    colors: [Color(0xFF121212), AppColors.background, Color(0xFF020202)],
  );

  static const LinearGradient tealGradient = LinearGradient(
    colors: [AppColors.accentSoft, AppColors.accent],
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
  );
}
