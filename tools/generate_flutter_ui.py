"""Script to generate Flutter UI files for the futuristic redesign."""
import os

# Ensure directories exist
widgets_dir = "chintu_ui/lib/widgets"
screens_dir = "chintu_ui/lib/screens"
os.makedirs(widgets_dir, exist_ok=True)
os.makedirs(screens_dir, exist_ok=True)

# AI Orb widget
ai_orb_content = '''import 'dart:math';
import 'package:flutter/material.dart';

class OrbColors {
  static const Color idle = Color(0xFF4F46E5);
  static const Color listening = Color(0xFF10B981);
  static const Color processing = Color(0xFF8B5CF6);
  static const Color speaking = Color(0xFF06B6D4);
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
                  _orbColor.withOpacity(0.9),
                  _orbColor.withOpacity(0.6),
                  _orbColor.withOpacity(0.3),
                  Colors.transparent,
                ],
                stops: const [0.0, 0.4, 0.7, 1.0],
              ),
              boxShadow: [
                BoxShadow(
                  color: _orbColor.withOpacity(0.5),
                  blurRadius: 60,
                  spreadRadius: 20,
                ),
              ],
            ),
            child: Center(
              child: Icon(
                _getIcon(),
                color: Colors.white.withOpacity(0.9),
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
      case 'listening': text = 'Listening...'; break;
      case 'processing': text = 'Processing...'; break;
      case 'speaking': text = 'Speaking...'; break;
      default: text = 'Say "Hey Chintu"';
    }
    return Text(
      text,
      style: TextStyle(
        color: Colors.white.withOpacity(0.8),
        fontSize: 18,
        fontWeight: FontWeight.w300,
        letterSpacing: 1.5,
      ),
    );
  }
}
'''

# Glass card widget
glass_card_content = '''import 'dart:ui';
import 'package:flutter/material.dart';

class GlassCard extends StatelessWidget {
  final Widget child;
  final double blur;
  final double opacity;
  final EdgeInsets padding;
  final BorderRadius? borderRadius;
  
  const GlassCard({
    super.key,
    required this.child,
    this.blur = 10,
    this.opacity = 0.1,
    this.padding = const EdgeInsets.all(16),
    this.borderRadius,
  });
  
  @override
  Widget build(BuildContext context) {
    return ClipRRect(
      borderRadius: borderRadius ?? BorderRadius.circular(20),
      child: BackdropFilter(
        filter: ImageFilter.blur(sigmaX: blur, sigmaY: blur),
        child: Container(
          padding: padding,
          decoration: BoxDecoration(
            color: Colors.white.withOpacity(opacity),
            borderRadius: borderRadius ?? BorderRadius.circular(20),
            border: Border.all(
              color: Colors.white.withOpacity(0.2),
              width: 1,
            ),
          ),
          child: child,
        ),
      ),
    );
  }
}
'''

# New futuristic home screen
home_screen_content = '''import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/websocket_service.dart';
import '../widgets/ai_orb.dart';
import '../widgets/glass_card.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});
  @override State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final TextEditingController _textController = TextEditingController();
  final ScrollController _scrollController = ScrollController();
  
  @override
  void dispose() {
    _textController.dispose();
    _scrollController.dispose();
    super.dispose();
  }
  
  @override
  Widget build(BuildContext context) {
    return Consumer<WebSocketService>(
      builder: (context, ws, child) {
        final state = ws.assistantState;
        final audioLevel = ws.audioLevel;
        final messages = ws.messages;
        
        return Scaffold(
          body: Container(
            decoration: const BoxDecoration(
              gradient: LinearGradient(
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
                colors: [
                  Color(0xFF0F0F23),
                  Color(0xFF1A1A3E),
                  Color(0xFF0F0F23),
                ],
              ),
            ),
            child: SafeArea(
              child: Row(
                children: [
                  // Main content - AI Orb
                  Expanded(
                    flex: 3,
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        // Title
                        const Text(
                          'CHINTU',
                          style: TextStyle(
                            fontSize: 32,
                            fontWeight: FontWeight.w200,
                            letterSpacing: 12,
                            color: Colors.white,
                          ),
                        ),
                        const SizedBox(height: 8),
                        Text(
                          'Personal AI Assistant',
                          style: TextStyle(
                            fontSize: 14,
                            color: Colors.white.withOpacity(0.5),
                            letterSpacing: 2,
                          ),
                        ),
                        const SizedBox(height: 60),
                        
                        // AI Orb
                        AIOrb(
                          state: state,
                          audioLevel: audioLevel,
                          size: 220,
                        ),
                        const SizedBox(height: 40),
                        
                        // State indicator
                        StateIndicator(state: state),
                        const SizedBox(height: 60),
                        
                        // Connection status
                        _buildConnectionStatus(ws.isConnected),
                      ],
                    ),
                  ),
                  
                  // Chat panel
                  Container(
                    width: 350,
                    margin: const EdgeInsets.all(20),
                    child: GlassCard(
                      blur: 15,
                      opacity: 0.08,
                      padding: EdgeInsets.zero,
                      child: Column(
                        children: [
                          // Header
                          Container(
                            padding: const EdgeInsets.all(16),
                            decoration: BoxDecoration(
                              border: Border(
                                bottom: BorderSide(
                                  color: Colors.white.withOpacity(0.1),
                                ),
                              ),
                            ),
                            child: Row(
                              children: [
                                Icon(Icons.chat_bubble_outline, 
                                     color: Colors.white.withOpacity(0.7), size: 20),
                                const SizedBox(width: 10),
                                Text('Conversation',
                                     style: TextStyle(color: Colors.white.withOpacity(0.9),
                                                      fontWeight: FontWeight.w500)),
                              ],
                            ),
                          ),
                          
                          // Messages
                          Expanded(
                            child: ListView.builder(
                              controller: _scrollController,
                              padding: const EdgeInsets.all(16),
                              itemCount: messages.length,
                              itemBuilder: (context, index) {
                                final msg = messages[index];
                                return _buildMessageBubble(msg);
                              },
                            ),
                          ),
                          
                          // Input
                          Container(
                            padding: const EdgeInsets.all(12),
                            decoration: BoxDecoration(
                              border: Border(
                                top: BorderSide(color: Colors.white.withOpacity(0.1)),
                              ),
                            ),
                            child: Row(
                              children: [
                                Expanded(
                                  child: TextField(
                                    controller: _textController,
                                    style: const TextStyle(color: Colors.white),
                                    decoration: InputDecoration(
                                      hintText: 'Type a command...',
                                      hintStyle: TextStyle(color: Colors.white.withOpacity(0.4)),
                                      border: InputBorder.none,
                                      contentPadding: const EdgeInsets.symmetric(horizontal: 12),
                                    ),
                                    onSubmitted: (text) => _sendMessage(ws, text),
                                  ),
                                ),
                                IconButton(
                                  icon: Icon(Icons.send, color: Colors.white.withOpacity(0.7)),
                                  onPressed: () => _sendMessage(ws, _textController.text),
                                ),
                              ],
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        );
      },
    );
  }
  
  Widget _buildConnectionStatus(bool connected) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 8, height: 8,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            color: connected ? Colors.green : Colors.red,
            boxShadow: [
              BoxShadow(
                color: (connected ? Colors.green : Colors.red).withOpacity(0.5),
                blurRadius: 6,
              ),
            ],
          ),
        ),
        const SizedBox(width: 8),
        Text(
          connected ? 'Connected' : 'Disconnected',
          style: TextStyle(
            color: Colors.white.withOpacity(0.5),
            fontSize: 12,
          ),
        ),
      ],
    );
  }
  
  Widget _buildMessageBubble(Map<String, dynamic> msg) {
    final isUser = msg['role'] == 'user';
    return Align(
      alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.only(bottom: 12),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        constraints: const BoxConstraints(maxWidth: 280),
        decoration: BoxDecoration(
          color: isUser 
              ? Colors.purple.withOpacity(0.3)
              : Colors.white.withOpacity(0.1),
          borderRadius: BorderRadius.circular(16),
          border: Border.all(
            color: isUser 
                ? Colors.purple.withOpacity(0.4)
                : Colors.white.withOpacity(0.1),
          ),
        ),
        child: Text(
          msg['content'] ?? '',
          style: TextStyle(
            color: Colors.white.withOpacity(0.9),
            fontSize: 14,
          ),
        ),
      ),
    );
  }
  
  void _sendMessage(WebSocketService ws, String text) {
    if (text.trim().isEmpty) return;
    ws.sendCommand(text);
    _textController.clear();
  }
}
'''

# Write files
with open(f"{widgets_dir}/ai_orb.dart", "w", encoding="utf-8") as f:
    f.write(ai_orb_content)
print(f"Created {widgets_dir}/ai_orb.dart")

with open(f"{widgets_dir}/glass_card.dart", "w", encoding="utf-8") as f:
    f.write(glass_card_content)
print(f"Created {widgets_dir}/glass_card.dart")

with open(f"{screens_dir}/home_screen.dart", "w", encoding="utf-8") as f:
    f.write(home_screen_content)
print(f"Created {screens_dir}/home_screen.dart")

print("\\nAll Flutter UI files generated successfully!")
