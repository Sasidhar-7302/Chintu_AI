import 'package:flutter/material.dart';

import '../theme/app_theme.dart';

class AIOrb extends StatefulWidget {
  final String state;
  final double audioLevel;
  final double size;

  const AIOrb({
    super.key,
    this.state = 'idle',
    this.audioLevel = 0.0,
    this.size = 180,
  });

  @override
  State<AIOrb> createState() => _AIOrbState();
}

class _AIOrbState extends State<AIOrb> with SingleTickerProviderStateMixin {
  late final AnimationController _pulse;

  @override
  void initState() {
    super.initState();
    _pulse = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1350),
    )..repeat(reverse: true);
  }

  @override
  void dispose() {
    _pulse.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final baseColor = _stateColor(widget.state);
    final levelScale = 1 + (widget.audioLevel.clamp(0, 1) * 0.12);

    return AnimatedBuilder(
      animation: _pulse,
      builder: (context, child) {
        final pulseScale = 0.96 + (_pulse.value * 0.08);
        return Transform.scale(
          scale: pulseScale * levelScale,
          child: Container(
            width: widget.size,
            height: widget.size,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: AppColors.surfaceStrong,
              border: Border.all(
                color: baseColor.withValues(alpha: 0.72),
                width: 2,
              ),
              boxShadow: [
                BoxShadow(
                  color: baseColor.withValues(alpha: 0.12),
                  blurRadius: 16,
                  spreadRadius: 1,
                ),
              ],
            ),
            child: Center(
              child: Container(
                width: widget.size * 0.45,
                height: widget.size * 0.45,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: baseColor.withValues(alpha: 0.16),
                  border: Border.all(
                    color: baseColor.withValues(alpha: 0.5),
                    width: 1.2,
                  ),
                ),
              ),
            ),
          ),
        );
      },
    );
  }

  Color _stateColor(String state) {
    switch (state.toLowerCase()) {
      case 'standby':
        return AppColors.accent;
      case 'listening':
        return AppColors.accentSoft;
      case 'processing':
        return AppColors.accentDeep;
      case 'speaking':
        return AppColors.accent;
      default:
        return AppColors.borderStrong;
    }
  }
}

class StateIndicator extends StatelessWidget {
  final String state;

  const StateIndicator({super.key, required this.state});

  @override
  Widget build(BuildContext context) {
    return Text(
      _label(state),
      textAlign: TextAlign.center,
      style: const TextStyle(
        color: AppColors.textMuted,
        fontSize: 14,
        fontWeight: FontWeight.w500,
      ),
    );
  }

  String _label(String current) {
    switch (current.toLowerCase()) {
      case 'standby':
        return 'Ready';
      case 'listening':
        return 'Listening';
      case 'processing':
        return 'Thinking';
      case 'speaking':
        return 'Responding';
      case 'error':
        return 'Disconnected';
      default:
        return 'Idle';
    }
  }
}
