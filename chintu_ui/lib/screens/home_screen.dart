import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:window_manager/window_manager.dart';
import '../services/websocket_service.dart';
import '../widgets/ai_orb.dart';
import '../widgets/waveform_widget.dart';
import '../widgets/glass_card.dart';
import '../widgets/capability_panel.dart';
import '../widgets/code_approval_dialog.dart';
import '../theme/app_theme.dart';
import 'settings_screen.dart';
import 'dart:async';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});
  @override State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final TextEditingController _textController = TextEditingController();
  final ScrollController _scrollController = ScrollController();
  bool _isRecording = false;
  StreamSubscription? _approvalSubscription;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final ws = context.read<WebSocketService>();
      _approvalSubscription = ws.approvalRequests.listen(_showApprovalDialog);
    });
  }

  @override
  void dispose() {
    _approvalSubscription?.cancel();
    _textController.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  void _showApprovalDialog(Map<String, dynamic> request) {
    if (!mounted) return;
    
    // Bring window to front
    // windowManager.show(); // Assuming handled by backend 'window_control'

    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (context) => CodeApprovalDialog(
        fileName: request['file'] ?? 'Unknown File',
        diff: request['diff'] ?? 'No diff available',
        onApprove: () {
          context.read<WebSocketService>().sendCodeApprovalResponse(
            request['request_id'], true
          );
          Navigator.of(context).pop();
        },
        onReject: () {
          context.read<WebSocketService>().sendCodeApprovalResponse(
            request['request_id'], false
          );
          Navigator.of(context).pop();
        },
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Consumer<WebSocketService>(
      builder: (context, ws, child) {
        final state = ws.assistantState;
        final audioLevel = ws.audioLevel;
        final messages = ws.messages;
        final capabilities = ws.capabilities;
        final transcript = ws.transcript;
        final connected = ws.isConnected;
        final isStandby = connected && state == 'idle';
        final displayState = !connected ? 'error' : (isStandby ? 'standby' : state);
        final showWaveform = displayState == 'listening' || displayState == 'speaking' || displayState == 'standby';
        final waveformActive = displayState == 'listening' || displayState == 'speaking';
        final waveformColor = displayState == 'speaking'
            ? AppColors.accentSoft
            : AppColors.accent;
        final waveformLevel = waveformActive ? audioLevel : (audioLevel * 0.35);

        final displayMessages = List<Map<String, dynamic>>.from(messages);

        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (_scrollController.hasClients && displayMessages.isNotEmpty) {
            _scrollController.jumpTo(_scrollController.position.maxScrollExtent);
          }
          if ((state == 'listening' || state == 'processing') && transcript.isNotEmpty) {
            if (_textController.text != transcript) {
              _textController.value = TextEditingValue(
                text: transcript,
                selection: TextSelection.collapsed(offset: transcript.length),
              );
            }
          } else if (state == 'idle' && transcript.isNotEmpty && _textController.text == transcript) {
            _textController.clear();
          }
        });

        return Scaffold(
          body: Container(
            decoration: const BoxDecoration(gradient: AppTheme.appBackground),
            child: Stack(
              children: [
                _buildBackdrop(),
                SafeArea(
                  child: LayoutBuilder(
                    builder: (context, constraints) {
                      final isCompact = constraints.maxWidth < 1100;
                      return Column(
                        children: [
                          _buildTopBar(theme, connected, displayState),
                          const SizedBox(height: 12),
                          Expanded(
                            child: isCompact
                                ? _buildCompactLayout(
                                    theme,
                                    connected,
                                    displayState,
                                    showWaveform,
                                    waveformActive,
                                    waveformLevel,
                                    waveformColor,
                                    audioLevel,
                                    capabilities,
                                    displayMessages,
                                  )
                                : _buildWideLayout(
                                    theme,
                                    connected,
                                    displayState,
                                    showWaveform,
                                    waveformActive,
                                    waveformLevel,
                                    waveformColor,
                                    audioLevel,
                                    capabilities,
                                    displayMessages,
                                  ),
                          ),
                        ],
                      );
                    },
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }

  Widget _buildBackdrop() {
    return Stack(
      children: [
        Positioned(
          top: -120,
          left: -80,
          child: _blurredOrb(color: AppColors.accent.withValues(alpha: 0.25), size: 260),
        ),
        Positioned(
          bottom: -120,
          right: -60,
          child: _blurredOrb(color: AppColors.accentSoft.withValues(alpha: 0.2), size: 240),
        ),
        Positioned(
          top: 200,
          right: 220,
          child: _blurredOrb(color: AppColors.success.withValues(alpha: 0.15), size: 180),
        ),
      ],
    );
  }

  Widget _blurredOrb({required Color color, required double size}) {
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        color: color,
        boxShadow: [
          BoxShadow(
            color: color,
            blurRadius: 120,
            spreadRadius: 30,
          ),
        ],
      ),
    );
  }

  Widget _buildTopBar(ThemeData theme, bool connected, String displayState) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 6),
      child: Row(
        children: [
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('CHINTU', style: theme.textTheme.displayLarge),
              const SizedBox(height: 4),
              Text('Personal AI Assistant', style: theme.textTheme.labelLarge),
            ],
          ),
          const Spacer(),
          _buildStatusChip(displayState, connected),
          const SizedBox(width: 12),
          _buildConnectionStatus(connected),
          const SizedBox(width: 12),
          _buildWindowButton(Icons.settings, () => Navigator.push(context, MaterialPageRoute(builder: (_) => const SettingsScreen()))),
          const SizedBox(width: 8),
          _buildWindowButton(Icons.close, () async => await windowManager.close()),
        ],
      ),
    );
  }

  Widget _buildWideLayout(
    ThemeData theme,
    bool connected,
    String displayState,
    bool showWaveform,
    bool waveformActive,
    double waveformLevel,
    Color waveformColor,
    double audioLevel,
    List<Map<String, dynamic>> capabilities,
    List<Map<String, dynamic>> displayMessages,
  ) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 10, 16, 16),
      child: Row(
        children: [
          SizedBox(
            width: 240,
            child: CapabilityPanel(capabilities: capabilities),
          ),
          const SizedBox(width: 18),
          Expanded(
            flex: 2,
            child: _buildCenterPanel(
              theme,
              connected,
              displayState,
              showWaveform,
              waveformActive,
              waveformLevel,
              waveformColor,
              audioLevel,
            ),
          ),
          const SizedBox(width: 18),
          SizedBox(
            width: 360,
            child: _buildConversationPanel(theme, connected, displayMessages),
          ),
        ],
      ),
    );
  }

  Widget _buildCompactLayout(
    ThemeData theme,
    bool connected,
    String displayState,
    bool showWaveform,
    bool waveformActive,
    double waveformLevel,
    Color waveformColor,
    double audioLevel,
    List<Map<String, dynamic>> capabilities,
    List<Map<String, dynamic>> displayMessages,
  ) {
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(16, 10, 16, 16),
      child: Column(
        children: [
          _buildCenterPanel(
            theme,
            connected,
            displayState,
            showWaveform,
            waveformActive,
            waveformLevel,
            waveformColor,
            audioLevel,
          ),
          const SizedBox(height: 16),
          _buildConversationPanel(theme, connected, displayMessages),
          const SizedBox(height: 16),
          CapabilityPanel(capabilities: capabilities),
        ],
      ),
    );
  }

  Widget _buildCenterPanel(
    ThemeData theme,
    bool connected,
    String displayState,
    bool showWaveform,
    bool waveformActive,
    double waveformLevel,
    Color waveformColor,
    double audioLevel,
  ) {
    return GlassCard(
      blur: 20,
      opacity: 0.22,
      borderRadius: BorderRadius.circular(24),
      padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 28),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Align(
            alignment: Alignment.centerLeft,
            child: Text(
              'Assistant Core',
              style: theme.textTheme.titleLarge,
            ),
          ),
          const SizedBox(height: 18),
          Center(
            child: showWaveform
                ? SizedBox(
                    height: 220,
                    child: WaveformWidget(
                      audioLevel: waveformLevel,
                      isActive: waveformActive,
                      color: waveformColor,
                    ),
                  )
                : AIOrb(state: displayState, audioLevel: audioLevel, size: 220),
          ),
          const SizedBox(height: 18),
          StateIndicator(state: displayState),
          const SizedBox(height: 14),
          _buildHintRow(displayState, connected),
        ],
      ),
    );
  }

  Widget _buildConversationPanel(ThemeData theme, bool connected, List<Map<String, dynamic>> displayMessages) {
    return GlassCard(
      blur: 18,
      opacity: 0.2,
      borderRadius: BorderRadius.circular(22),
      padding: EdgeInsets.zero,
      child: Column(
        children: [
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: AppColors.surfaceStrong.withValues(alpha: 0.6),
              borderRadius: const BorderRadius.vertical(top: Radius.circular(22)),
              border: Border(
                bottom: BorderSide(color: AppColors.border.withValues(alpha: 0.6)),
              ),
            ),
            child: Row(
              children: [
                Container(
                  padding: const EdgeInsets.all(8),
                  decoration: BoxDecoration(
                    color: AppColors.accent.withValues(alpha: 0.15),
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: const Icon(Icons.chat_bubble_outline, color: AppColors.accent, size: 16),
                ),
                const SizedBox(width: 12),
                Text('Conversation', style: theme.textTheme.titleLarge),
              ],
            ),
          ),
          Expanded(
            child: displayMessages.isEmpty
                ? Center(
                    child: Text(
                      connected ? 'Wake word active - say "Hey Chintu"' : 'Waiting for backend...',
                      style: theme.textTheme.bodySmall,
                      textAlign: TextAlign.center,
                    ),
                  )
                : ListView.builder(
                    controller: _scrollController,
                    padding: const EdgeInsets.all(16),
                    itemCount: displayMessages.length,
                    itemBuilder: (context, index) => _buildMessageBubble(displayMessages[index]),
                  ),
          ),
          _buildInputBar(theme),
        ],
      ),
    );
  }

  Widget _buildInputBar(ThemeData theme) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppColors.surfaceStrong.withValues(alpha: 0.5),
        border: Border(top: BorderSide(color: AppColors.border.withValues(alpha: 0.6))),
      ),
      child: Row(
        children: [
          GestureDetector(
            onTapDown: (_) => _startRecording(context.read<WebSocketService>()),
            onTapUp: (_) => _stopRecording(context.read<WebSocketService>()),
            onTapCancel: () => _stopRecording(context.read<WebSocketService>()),
            child: Container(
              width: 40,
              height: 40,
              margin: const EdgeInsets.only(right: 8),
              decoration: BoxDecoration(
                color: _isRecording ? AppColors.danger.withValues(alpha: 0.7) : AppColors.accent.withValues(alpha: 0.12),
                borderRadius: BorderRadius.circular(20),
                border: Border.all(color: _isRecording ? AppColors.danger : AppColors.accent.withValues(alpha: 0.4)),
              ),
              child: Icon(
                _isRecording ? Icons.mic : Icons.mic_none,
                color: _isRecording ? Colors.white : AppColors.accent,
                size: 18,
              ),
            ),
          ),
          Expanded(
            child: TextField(
              controller: _textController,
              style: theme.textTheme.bodyMedium,
              decoration: InputDecoration(
                hintText: 'Type a command...',
                hintStyle: theme.textTheme.bodySmall,
                border: InputBorder.none,
                contentPadding: const EdgeInsets.symmetric(horizontal: 10),
              ),
              onSubmitted: (text) => _sendMessage(context.read<WebSocketService>(), text),
            ),
          ),
          IconButton(
            icon: const Icon(Icons.send, color: AppColors.accent, size: 20),
            onPressed: () => _sendMessage(context.read<WebSocketService>(), _textController.text),
          ),
        ],
      ),
    );
  }

  Widget _buildStatusChip(String displayState, bool connected) {
    final Map<String, Color> colors = {
      'standby': AppColors.accent,
      'listening': AppColors.success,
      'processing': AppColors.warning,
      'speaking': AppColors.accentSoft,
      'error': AppColors.danger,
    };
    final label = switch (displayState) {
      'standby' => 'Wake word active',
      'listening' => 'Listening',
      'processing' => 'Thinking',
      'speaking' => 'Speaking',
      'error' => 'Disconnected',
      _ => 'Idle',
    };
    final color = colors[displayState] ?? AppColors.textMuted;

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      decoration: BoxDecoration(
        color: color.withValues(alpha: connected ? 0.15 : 0.08),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: color.withValues(alpha: 0.5)),
      ),
      child: Text(
        label,
        style: TextStyle(
          color: color,
          fontSize: 12,
          fontWeight: FontWeight.w600,
          letterSpacing: 0.4,
        ),
      ),
    );
  }

  Widget _buildHintRow(String displayState, bool connected) {
    final hint = switch (displayState) {
      'speaking' => 'Say "Hey Chintu" to interrupt',
      'listening' => 'Speak naturally - I am listening',
      'standby' => 'Say "Hey Chintu" anytime',
      _ => connected ? 'Wake word stays active in the background' : 'Waiting for backend connection',
    };
    return Row(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        const Icon(Icons.info_outline, color: AppColors.textMuted, size: 14),
        const SizedBox(width: 6),
        Text(
          hint,
          style: const TextStyle(
            color: AppColors.textMuted,
            fontSize: 12,
          ),
        ),
      ],
    );
  }

  void _startRecording(WebSocketService ws) {
    setState(() => _isRecording = true);
    ws.startPushToTalk();
  }

  void _stopRecording(WebSocketService ws) {
    setState(() => _isRecording = false);
    ws.stopPushToTalk();
  }

  Widget _buildWindowButton(IconData icon, VoidCallback onPressed) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onPressed,
        borderRadius: BorderRadius.circular(10),
        child: Container(
          width: 36,
          height: 36,
          decoration: BoxDecoration(
            color: AppColors.surfaceStrong.withValues(alpha: 0.5),
            borderRadius: BorderRadius.circular(10),
            border: Border.all(color: AppColors.border.withValues(alpha: 0.6)),
          ),
          child: Icon(icon, color: AppColors.textPrimary.withValues(alpha: 0.9), size: 18),
        ),
      ),
    );
  }

  Widget _buildConnectionStatus(bool connected) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 8,
          height: 8,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            color: connected ? AppColors.success : AppColors.danger,
            boxShadow: [
              BoxShadow(
                color: (connected ? AppColors.success : AppColors.danger).withValues(alpha: 0.5),
                blurRadius: 6,
              )
            ],
          ),
        ),
        const SizedBox(width: 8),
        Text(
          connected ? 'Connected' : 'Disconnected',
          style: const TextStyle(color: AppColors.textMuted, fontSize: 12),
        ),
      ],
    );
  }

  Widget _buildMessageBubble(Map<String, dynamic> msg) {
    final isUser = msg['role'] == 'user';
    final isSystem = msg['role'] == 'system';
    final isPartial = msg['isPartial'] == true;
    final bubbleColor = isUser
        ? AppColors.accent.withValues(alpha: 0.15)
        : (isSystem ? AppColors.danger.withValues(alpha: 0.12) : AppColors.surfaceStrong.withValues(alpha: 0.7));
    final borderColor = isUser
        ? AppColors.accent.withValues(alpha: 0.5)
        : (isSystem ? AppColors.danger.withValues(alpha: 0.45) : AppColors.border.withValues(alpha: 0.6));

    return Align(
      alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.only(bottom: 10),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        constraints: const BoxConstraints(maxWidth: 280),
        decoration: BoxDecoration(
          color: bubbleColor,
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: borderColor),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (isPartial) ...[
              SizedBox(
                width: 12,
                height: 12,
                child: CircularProgressIndicator(
                  strokeWidth: 2,
                  color: AppColors.accent.withValues(alpha: 0.7),
                ),
              ),
              const SizedBox(width: 8),
            ],
            Flexible(
              child: Text(
                msg['content'] ?? msg['text'] ?? '',
                style: TextStyle(
                  color: AppColors.textPrimary.withValues(alpha: isPartial ? 0.8 : 1.0),
                  fontSize: 13,
                  fontStyle: isPartial ? FontStyle.italic : FontStyle.normal,
                ),
              ),
            ),
          ],
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
