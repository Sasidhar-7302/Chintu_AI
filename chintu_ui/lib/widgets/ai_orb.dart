import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

class OrbColors {
  static const Color idle = AppColors.accentSoft;
  static const Color standby = AppColors.accent;
  static const Color listening = AppColors.success;
  static const Color processing = AppColors.warning;
  static const Color speaking = AppColors.accent;
}

class AIOrb extends StatefulWidget {
  final String state;
  final double audioLevel;
  final double size;
  const AIOrb({super.key, this.state = 'idle', this.audioLevel = 0.0, this.size = 200});
  @override State<AIOrb> createState() => _AIOrbState();
}

class _AIOrbState extends State<AIOrb> with TickerProviderStateMixin {
  late AnimationController _pulseController;
  late Animation<double> _pulseAnimation;
  
  @override
  void initState() {
    super.initState();
    _pulseController = AnimationController(
      duration: const Duration(milliseconds: 1500),
      vsync: this,
    )..repeat(reverse: true);
    _pulseAnimation = Tween<double>(begin: 0.95, end: 1.05).animate(
      CurvedAnimation(parent: _pulseController, curve: Curves.easeInOut),
    );
  }
  
  @override
  void dispose() {
    _pulseController.dispose();
    super.dispose();
  }
  
  Color get _orbColor {
    switch (widget.state.toLowerCase()) {
      case 'standby': return OrbColors.standby;
      case 'listening': return OrbColors.listening;
      case 'processing': return OrbColors.processing;
      case 'speaking': return OrbColors.speaking;
      default: return OrbColors.idle;
    }
  }
  
  @override
  Widget build(BuildContext context) {
    final scale = 1.0 + (widget.audioLevel * 0.15);
    return AnimatedBuilder(
      animation: _pulseAnimation,
      builder: (context, child) {
        return Transform.scale(
          scale: _pulseAnimation.value * scale,
          child: Container(
            width: widget.size,
            height: widget.size,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              gradient: RadialGradient(
                colors: [
                  _orbColor.withValues(alpha: 0.9),
                  _orbColor.withValues(alpha: 0.6),
                  _orbColor.withValues(alpha: 0.3),
                  Colors.transparent,
                ],
                stops: const [0.0, 0.4, 0.7, 1.0],
              ),
              boxShadow: [
                BoxShadow(
                  color: _orbColor.withValues(alpha: 0.5),
                  blurRadius: 60,
                  spreadRadius: 20,
                ),
              ],
            ),
            child: Center(
              child: Icon(
                _getIcon(),
                color: Colors.white.withValues(alpha: 0.9),
                size: widget.size * 0.2,
              ),
            ),
          ),
        );
      },
    );
  }
  
  IconData _getIcon() {
    switch (widget.state.toLowerCase()) {
      case 'standby': return Icons.mic_none;
      case 'listening': return Icons.mic;
      case 'processing': return Icons.psychology;
      case 'speaking': return Icons.volume_up;
      default: return Icons.circle;
    }
  }
}

class StateIndicator extends StatelessWidget {
  final String state;
  const StateIndicator({super.key, required this.state});
  
  @override
  Widget build(BuildContext context) {
    String text;
    switch (state.toLowerCase()) {
      case 'standby': text = 'Wake word active'; break;
      case 'listening': text = 'Listening...'; break;
      case 'processing': text = 'Processing...'; break;
      case 'speaking': text = 'Speaking... Say "Hey Chintu" to interrupt'; break;
      case 'error': text = 'Disconnected'; break;
      default: text = 'Say "Hey Chintu"';
    }
    return Text(
      text,
      textAlign: TextAlign.center,
      style: TextStyle(
        color: AppColors.textPrimary.withValues(alpha: 0.85),
        fontSize: 18,
        fontWeight: FontWeight.w300,
        letterSpacing: 1.5,
      ),
    );
  }
}
