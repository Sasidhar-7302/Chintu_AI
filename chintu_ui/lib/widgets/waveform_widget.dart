import 'dart:math';
import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

/// Modern pulsing orb widget - ChatGPT/Gemini style
/// Displays smooth concentric rings that pulse based on audio level
class WaveformWidget extends StatefulWidget {
  final double audioLevel;
  final bool isActive;
  final Color color;

  const WaveformWidget({
    super.key,
    required this.audioLevel,
    this.isActive = true,
    this.color = AppColors.accent,
  });

  @override
  State<WaveformWidget> createState() => _WaveformWidgetState();
}

class _WaveformWidgetState extends State<WaveformWidget>
    with TickerProviderStateMixin {
  late AnimationController _pulseController;
  late AnimationController _rotateController;
  late Animation<double> _pulseAnimation;

  @override
  void initState() {
    super.initState();
    
    // Smooth pulse animation
    _pulseController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1500),
    );
    _pulseAnimation = Tween<double>(begin: 0.0, end: 1.0).animate(
      CurvedAnimation(parent: _pulseController, curve: Curves.easeInOut),
    );
    _pulseController.repeat(reverse: true);

    // Slow rotation for visual interest
    _rotateController = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 10),
    )..repeat();
  }

  @override
  void dispose() {
    _pulseController.dispose();
    _rotateController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: Listenable.merge([_pulseController, _rotateController]),
      builder: (context, child) {
        final pulseValue = _pulseAnimation.value;
        final audioScale = widget.isActive ? (1.0 + widget.audioLevel * 0.3) : 1.0;
        
        return SizedBox(
          width: 200,
          height: 200,
          child: CustomPaint(
            painter: _ModernOrbPainter(
              pulseValue: pulseValue,
              audioLevel: widget.audioLevel,
              audioScale: audioScale,
              isActive: widget.isActive,
              rotation: _rotateController.value * 2 * pi,
              color: widget.color,
            ),
          ),
        );
      },
    );
  }
}

class _ModernOrbPainter extends CustomPainter {
  final double pulseValue;
  final double audioLevel;
  final double audioScale;
  final bool isActive;
  final double rotation;
  final Color color;

  _ModernOrbPainter({
    required this.pulseValue,
    required this.audioLevel,
    required this.audioScale,
    required this.isActive,
    required this.rotation,
    required this.color,
  });

  @override
  void paint(Canvas canvas, Size size) {
    final center = Offset(size.width / 2, size.height / 2);
    final maxRadius = size.width / 2;

    // Background glow
    if (isActive) {
      final glowPaint = Paint()
        ..color = color.withValues(alpha: 0.1 + 0.1 * pulseValue)
        ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 30);
      canvas.drawCircle(center, maxRadius * 0.8 * audioScale, glowPaint);
    }

    // Concentric rings with varying opacity
    final ringCount = 4;
    for (int i = ringCount - 1; i >= 0; i--) {
      final ringProgress = i / ringCount;
      final baseRadius = maxRadius * (0.3 + ringProgress * 0.5);
      
      // Add pulse effect to each ring
      final ringPulse = sin(pulseValue * pi + i * 0.5) * 0.1;
      final radius = baseRadius * audioScale * (1.0 + ringPulse);
      
      // Opacity varies by ring and activity
      final baseOpacity = isActive ? (0.15 + (1 - ringProgress) * 0.25) : 0.1;
      final opacity = baseOpacity + (isActive ? audioLevel * 0.2 : 0);
      
      final ringPaint = Paint()
        ..color = color.withValues(alpha: opacity.clamp(0.0, 0.6))
        ..style = PaintingStyle.fill;
      
      canvas.drawCircle(center, radius, ringPaint);
    }

    // Center orb (solid)
    final centerRadius = maxRadius * 0.25 * audioScale;
    final centerGlow = Paint()
      ..color = color.withValues(alpha: isActive ? 0.4 : 0.2)
      ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 10);
    canvas.drawCircle(center, centerRadius * 1.2, centerGlow);
    
    final centerPaint = Paint()
      ..color = isActive ? color : color.withValues(alpha: 0.5)
      ..style = PaintingStyle.fill;
    canvas.drawCircle(center, centerRadius, centerPaint);

    // Animated dots around the orb when active
    if (isActive && audioLevel > 0.1) {
      final dotCount = 8;
      final dotRadius = 3.0 + audioLevel * 2;
      final orbitRadius = maxRadius * 0.6;
      
      for (int i = 0; i < dotCount; i++) {
        final angle = rotation + (i / dotCount) * 2 * pi;
        final dotX = center.dx + cos(angle) * orbitRadius;
        final dotY = center.dy + sin(angle) * orbitRadius;
        
        final dotOpacity = 0.3 + 0.4 * sin(pulseValue * pi + i);
        final dotPaint = Paint()
          ..color = Colors.white.withValues(alpha: dotOpacity.clamp(0.2, 0.7));
        
        canvas.drawCircle(Offset(dotX, dotY), dotRadius, dotPaint);
      }
    }
  }

  @override
  bool shouldRepaint(covariant _ModernOrbPainter oldDelegate) => true;
}
