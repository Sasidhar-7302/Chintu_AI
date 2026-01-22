import 'dart:math' as math;
import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

enum AssistantStatus { idle, listening, thinking, speaking, error }

class StatusIndicator extends StatefulWidget {
  final String status;
  final String? gesture;

  const StatusIndicator({
    super.key,
    required this.status,
    this.gesture,
  });

  @override
  State<StatusIndicator> createState() => _StatusIndicatorState();
}

class _StatusIndicatorState extends State<StatusIndicator>
    with TickerProviderStateMixin {
  late AnimationController _pulseController;
  late AnimationController _rotationController;
  late AnimationController _waveController;
  late AnimationController _bounceController;

  late Animation<double> _pulseAnimation;
  late Animation<double> _rotationAnimation;
  late Animation<double> _waveAnimation;
  late Animation<double> _bounceAnimation;

  @override
  void initState() {
    super.initState();

    // Pulse animation for listening
    _pulseController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1200),
    );
    _pulseAnimation = Tween<double>(begin: 0.95, end: 1.15).animate(
      CurvedAnimation(parent: _pulseController, curve: Curves.easeInOut),
    );

    // Rotation animation for thinking
    _rotationController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 2000),
    );
    _rotationAnimation = Tween<double>(begin: 0, end: 2 * math.pi).animate(
      CurvedAnimation(parent: _rotationController, curve: Curves.linear),
    );

    // Wave animation for speaking
    _waveController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 800),
    );
    _waveAnimation = Tween<double>(begin: 0, end: 1).animate(
      CurvedAnimation(parent: _waveController, curve: Curves.easeInOut),
    );

    // Bounce animation for idle
    _bounceController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 2000),
    );
    _bounceAnimation = Tween<double>(begin: 0, end: 1).animate(
      CurvedAnimation(parent: _bounceController, curve: Curves.easeInOut),
    );

    _bounceController.repeat(reverse: true);
  }

  @override
  void didUpdateWidget(StatusIndicator oldWidget) {
    super.didUpdateWidget(oldWidget);
    _updateAnimations();
  }

  void _updateAnimations() {
    // Stop all animations first
    _pulseController.stop();
    _rotationController.stop();
    _waveController.stop();

    switch (_assistantStatus) {
      case AssistantStatus.listening:
        _pulseController.repeat(reverse: true);
        break;
      case AssistantStatus.thinking:
        _rotationController.repeat();
        break;
      case AssistantStatus.speaking:
        _waveController.repeat(reverse: true);
        break;
      default:
        break;
    }
  }

  @override
  void dispose() {
    _pulseController.dispose();
    _rotationController.dispose();
    _waveController.dispose();
    _bounceController.dispose();
    super.dispose();
  }

  AssistantStatus get _assistantStatus {
    switch (widget.status.toLowerCase()) {
      case 'listening':
        return AssistantStatus.listening;
      case 'thinking':
      case 'processing':
        return AssistantStatus.thinking;
      case 'speaking':
      case 'responding':
        return AssistantStatus.speaking;
      case 'error':
        return AssistantStatus.error;
      default:
        return AssistantStatus.idle;
    }
  }

  Color get _statusColor {
    switch (_assistantStatus) {
      case AssistantStatus.listening:
        return AppColors.success;
      case AssistantStatus.thinking:
        return AppColors.warning;
      case AssistantStatus.speaking:
        return AppColors.accent;
      case AssistantStatus.error:
        return AppColors.danger;
      default:
        return AppColors.textMuted;
    }
  }

  Color get _secondaryColor {
    switch (_assistantStatus) {
      case AssistantStatus.listening:
        return AppColors.accentSoft;
      case AssistantStatus.thinking:
        return AppColors.warning.withValues(alpha: 0.7);
      case AssistantStatus.speaking:
        return AppColors.accentSoft;
      case AssistantStatus.error:
        return AppColors.danger.withValues(alpha: 0.7);
      default:
        return AppColors.textMuted.withValues(alpha: 0.7);
    }
  }

  IconData get _statusIcon {
    switch (_assistantStatus) {
      case AssistantStatus.listening:
        return Icons.mic;
      case AssistantStatus.thinking:
        return Icons.psychology;
      case AssistantStatus.speaking:
        return Icons.graphic_eq;
      case AssistantStatus.error:
        return Icons.error_outline;
      default:
        return Icons.radio_button_unchecked;
    }
  }

  String get _statusText {
    switch (_assistantStatus) {
      case AssistantStatus.listening:
        return 'Listening...';
      case AssistantStatus.thinking:
        return 'Thinking...';
      case AssistantStatus.speaking:
        return 'Speaking...';
      case AssistantStatus.error:
        return 'Error';
      default:
        return 'Say "Hey Chintu"';
    }
  }

  @override
  Widget build(BuildContext context) {
    WidgetsBinding.instance.addPostFrameCallback((_) => _updateAnimations());

    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        SizedBox(
          width: 160,
          height: 160,
          child: Stack(
            alignment: Alignment.center,
            children: [
              // Outer rotating rings for thinking
              if (_assistantStatus == AssistantStatus.thinking)
                ..._buildThinkingRings(),

              // Pulsing circles for listening
              if (_assistantStatus == AssistantStatus.listening)
                ..._buildListeningPulse(),

              // Speaking wave rings
              if (_assistantStatus == AssistantStatus.speaking)
                ..._buildSpeakingWaves(),

              // Idle breathing effect
              if (_assistantStatus == AssistantStatus.idle)
                _buildIdleBreathing(),

              // Error pulsing
              if (_assistantStatus == AssistantStatus.error)
                _buildErrorPulse(),

              // Main orb
              _buildMainOrb(),
            ],
          ),
        ),
        const SizedBox(height: 20),
        // Status text with animation
        AnimatedDefaultTextStyle(
          duration: const Duration(milliseconds: 300),
          style: TextStyle(
            color: _statusColor,
            fontSize: 18,
            fontWeight: FontWeight.w600,
            letterSpacing: 1,
          ),
          child: Text(_statusText),
        ),
        if (widget.gesture != null && widget.gesture!.isNotEmpty) ...[
          const SizedBox(height: 8),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
            decoration: BoxDecoration(
              color: AppColors.accentSoft.withValues(alpha: 0.2),
              borderRadius: BorderRadius.circular(20),
              border: Border.all(color: AppColors.accentSoft.withValues(alpha: 0.3)),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(Icons.pan_tool, color: AppColors.accentSoft, size: 16),
                const SizedBox(width: 6),
                Text(
                  widget.gesture!,
                  style: const TextStyle(
                    color: AppColors.accentSoft,
                    fontSize: 14,
                    fontWeight: FontWeight.w500,
                  ),
                ),
              ],
            ),
          ),
        ],
      ],
    );
  }

  Widget _buildMainOrb() {
    return AnimatedContainer(
      duration: const Duration(milliseconds: 300),
      width: 90,
      height: 90,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        gradient: RadialGradient(
          colors: [
            _statusColor.withValues(alpha: 0.4),
            _statusColor.withValues(alpha: 0.2),
            _secondaryColor.withValues(alpha: 0.1),
          ],
          stops: const [0.0, 0.5, 1.0],
        ),
        border: Border.all(color: _statusColor, width: 3),
        boxShadow: [
          BoxShadow(
            color: _statusColor.withValues(alpha: 0.6),
            blurRadius: 25,
            spreadRadius: 2,
          ),
          BoxShadow(
            color: _secondaryColor.withValues(alpha: 0.3),
            blurRadius: 50,
            spreadRadius: 5,
          ),
        ],
      ),
      child: AnimatedSwitcher(
        duration: const Duration(milliseconds: 200),
        child: Icon(
          _statusIcon,
          key: ValueKey(_statusIcon),
          color: _statusColor,
          size: 42,
        ),
      ),
    );
  }

  List<Widget> _buildListeningPulse() {
    return [
      // Multiple expanding circles
      for (int i = 0; i < 3; i++)
        AnimatedBuilder(
          animation: _pulseAnimation,
          builder: (context, child) {
            final delay = i * 0.2;
            final value = ((_pulseAnimation.value - 0.95) / 0.2 + delay) % 1.0;
            return Container(
              width: 90 + (70 * value),
              height: 90 + (70 * value),
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                border: Border.all(
                  color: _statusColor.withValues(alpha: 0.5 * (1 - value)),
                  width: 2,
                ),
              ),
            );
          },
        ),
    ];
  }

  List<Widget> _buildThinkingRings() {
    return [
      // Outer rotating ring
      AnimatedBuilder(
        animation: _rotationAnimation,
        builder: (context, child) {
          return Transform.rotate(
            angle: _rotationAnimation.value,
            child: CustomPaint(
              size: const Size(140, 140),
              painter: _ThinkingRingPainter(
                color: _statusColor,
                progress: _rotationController.value,
              ),
            ),
          );
        },
      ),
      // Inner counter-rotating ring
      AnimatedBuilder(
        animation: _rotationAnimation,
        builder: (context, child) {
          return Transform.rotate(
            angle: -_rotationAnimation.value * 1.5,
            child: CustomPaint(
              size: const Size(120, 120),
              painter: _ThinkingRingPainter(
                color: _secondaryColor,
                progress: _rotationController.value,
                dotCount: 6,
              ),
            ),
          );
        },
      ),
    ];
  }

  List<Widget> _buildSpeakingWaves() {
    return [
      AnimatedBuilder(
        animation: _waveAnimation,
        builder: (context, child) {
          return CustomPaint(
            size: const Size(150, 150),
            painter: _SpeakingWavePainter(
              color: _statusColor,
              secondaryColor: _secondaryColor,
              progress: _waveAnimation.value,
            ),
          );
        },
      ),
    ];
  }

  Widget _buildIdleBreathing() {
    return AnimatedBuilder(
      animation: _bounceAnimation,
      builder: (context, child) {
        return Container(
          width: 100 + (10 * _bounceAnimation.value),
          height: 100 + (10 * _bounceAnimation.value),
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            border: Border.all(
              color: _statusColor.withValues(alpha: 0.2 + (0.1 * _bounceAnimation.value)),
              width: 1,
            ),
          ),
        );
      },
    );
  }

  Widget _buildErrorPulse() {
    return AnimatedBuilder(
      animation: _bounceAnimation,
      builder: (context, child) {
        return Container(
          width: 110,
          height: 110,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            border: Border.all(
              color: _statusColor.withValues(alpha: 0.3 + (0.4 * _bounceAnimation.value)),
              width: 3,
            ),
          ),
        );
      },
    );
  }
}

// Custom painter for thinking ring with dots
class _ThinkingRingPainter extends CustomPainter {
  final Color color;
  final double progress;
  final int dotCount;

  _ThinkingRingPainter({
    required this.color,
    required this.progress,
    this.dotCount = 8,
  });

  @override
  void paint(Canvas canvas, Size size) {
    final center = Offset(size.width / 2, size.height / 2);
    final radius = size.width / 2 - 10;

    for (int i = 0; i < dotCount; i++) {
      final angle = (2 * math.pi / dotCount) * i;
      final dotRadius = 4.0 + (2.0 * math.sin((progress * 2 * math.pi) + (i * 0.5)));
      final x = center.dx + radius * math.cos(angle);
      final y = center.dy + radius * math.sin(angle);

      final paint = Paint()
        ..color = color.withValues(alpha: 0.3 + (0.7 * ((i + 1) / dotCount)))
        ..style = PaintingStyle.fill;

      canvas.drawCircle(Offset(x, y), dotRadius, paint);
    }
  }

  @override
  bool shouldRepaint(covariant _ThinkingRingPainter oldDelegate) => true;
}

// Custom painter for speaking waves
class _SpeakingWavePainter extends CustomPainter {
  final Color color;
  final Color secondaryColor;
  final double progress;

  _SpeakingWavePainter({
    required this.color,
    required this.secondaryColor,
    required this.progress,
  });

  @override
  void paint(Canvas canvas, Size size) {
    final center = Offset(size.width / 2, size.height / 2);

    // Draw multiple wave arcs
    for (int i = 0; i < 3; i++) {
      final radius = 55.0 + (i * 15);
      final opacity = 0.6 - (i * 0.15);
      final strokeWidth = 3.0 - (i * 0.5);

      final paint = Paint()
        ..color = (i % 2 == 0 ? color : secondaryColor).withValues(alpha: opacity * (0.5 + 0.5 * progress))
        ..style = PaintingStyle.stroke
        ..strokeWidth = strokeWidth
        ..strokeCap = StrokeCap.round;

      // Left arc
      canvas.drawArc(
        Rect.fromCircle(center: center, radius: radius),
        math.pi * 0.7,
        math.pi * 0.6 * progress,
        false,
        paint,
      );

      // Right arc
      canvas.drawArc(
        Rect.fromCircle(center: center, radius: radius),
        -math.pi * 0.3,
        math.pi * 0.6 * progress,
        false,
        paint,
      );
    }
  }

  @override
  bool shouldRepaint(covariant _SpeakingWavePainter oldDelegate) => true;
}
