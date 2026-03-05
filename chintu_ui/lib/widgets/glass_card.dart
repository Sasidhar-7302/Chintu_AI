import 'package:flutter/material.dart';
import '../theme/app_theme.dart';
import 'neon_panel.dart';

class GlassCard extends StatelessWidget {
  final Widget child;
  final EdgeInsets padding;
  final BorderRadius? borderRadius;

  const GlassCard({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.all(16),
    this.borderRadius,
  });

  @override
  Widget build(BuildContext context) {
    final radius = borderRadius ?? BorderRadius.circular(22);
    return NeonPanel(
      padding: padding,
      radius: radius.topLeft.x,
      borderWidth: 1.0,
      blur: 10,
      glowColor: AppColors.accent,
      showGlow: false,
      child: child,
    );
  }
}
