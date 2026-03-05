import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

class BackgroundGrid extends StatelessWidget {
  final double spacing;
  final double lineOpacity;

  const BackgroundGrid({
    super.key,
    this.spacing = 80,
    this.lineOpacity = 0.08,
  });

  @override
  Widget build(BuildContext context) {
    return CustomPaint(
      painter: _GridPainter(
        spacing: spacing,
        lineOpacity: lineOpacity,
      ),
    );
  }
}

class _GridPainter extends CustomPainter {
  final double spacing;
  final double lineOpacity;

  _GridPainter({required this.spacing, required this.lineOpacity});

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = AppColors.border.withValues(alpha: lineOpacity)
      ..strokeWidth = 1;

    for (double x = 0; x <= size.width; x += spacing) {
      canvas.drawLine(Offset(x, 0), Offset(x, size.height), paint);
    }
    for (double y = 0; y <= size.height; y += spacing) {
      canvas.drawLine(Offset(0, y), Offset(size.width, y), paint);
    }
  }

  @override
  bool shouldRepaint(covariant _GridPainter oldDelegate) {
    return oldDelegate.spacing != spacing || oldDelegate.lineOpacity != lineOpacity;
  }
}
