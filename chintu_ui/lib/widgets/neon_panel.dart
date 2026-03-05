import 'dart:ui';
import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

class NeonPanel extends StatelessWidget {
  final Widget child;
  final EdgeInsets padding;
  final double radius;
  final double borderWidth;
  final double blur;
  final Color? glowColor;
  final bool showGlow;

  const NeonPanel({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.all(16),
    this.radius = 20,
    this.borderWidth = 1.2,
    this.blur = 16,
    this.glowColor,
    this.showGlow = true,
  });

  @override
  Widget build(BuildContext context) {
    final glow = glowColor ?? AppColors.accent;
    final borderRadius = BorderRadius.circular(radius);
    return ClipRRect(
      borderRadius: borderRadius,
      child: BackdropFilter(
        filter: ImageFilter.blur(sigmaX: blur, sigmaY: blur),
        child: Container(
          decoration: BoxDecoration(
            color: AppColors.surface.withValues(alpha: 0.86),
            borderRadius: borderRadius,
            border: Border.all(color: AppColors.border.withValues(alpha: 0.9)),
            boxShadow: showGlow
                ? [
                    BoxShadow(
                      color: glow.withValues(alpha: 0.06),
                      blurRadius: 18,
                      spreadRadius: 1,
                      offset: const Offset(0, 6),
                    ),
                  ]
                : [],
          ),
          padding: EdgeInsets.all(borderWidth),
          child: Container(
            padding: padding,
            decoration: BoxDecoration(
              color: AppColors.surfaceStrong.withValues(alpha: 0.9),
              borderRadius: BorderRadius.circular(radius - borderWidth),
              border: Border.all(
                color: showGlow
                    ? glow.withValues(alpha: 0.18)
                    : AppColors.borderStrong.withValues(alpha: 0.55),
              ),
            ),
            child: child,
          ),
        ),
      ),
    );
  }
}
