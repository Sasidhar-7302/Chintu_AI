import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:window_manager/window_manager.dart';

import '../main.dart';
import '../services/websocket_service.dart';
import '../theme/app_theme.dart';
import '../widgets/a2ui_overlay.dart';
import '../widgets/ai_orb.dart';
import '../widgets/code_approval_dialog.dart';
import '../widgets/dashboard_panel.dart';
import '../widgets/glass_card.dart';
import '../widgets/waveform_widget.dart';
import 'settings_screen.dart';

/// Main production UI: minimal, high signal, dark-first with restrained teal.
class HomeScreenClean extends StatefulWidget {
  const HomeScreenClean({super.key});

  @override
  State<HomeScreenClean> createState() => _HomeScreenCleanState();
}

class _HomeScreenCleanState extends State<HomeScreenClean> {
  final TextEditingController _textController = TextEditingController();
  final ScrollController _scrollController = ScrollController();

  bool _isRecording = false;
  bool _showInfoPanel = false;
  StreamSubscription<Map<String, dynamic>>? _approvalSubscription;

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
    Future<void>.delayed(const Duration(milliseconds: 120), () {
      if (!mounted) return;
      final ws = context.read<WebSocketService>();
      if (ws.hasA2UIView(category: 'code_approval') ||
          ws.hasA2UIView(kind: 'code_approval')) {
        return;
      }
      showDialog<void>(
        context: context,
        barrierDismissible: false,
        builder: (context) => CodeApprovalDialog(
          fileName: request['file']?.toString() ?? 'Unknown File',
          diff: request['diff']?.toString() ?? 'No diff available',
          onApprove: () {
            context.read<WebSocketService>().sendCodeApprovalResponse(
              request['request_id'],
              true,
            );
            Navigator.of(context).pop();
          },
          onReject: () {
            context.read<WebSocketService>().sendCodeApprovalResponse(
              request['request_id'],
              false,
            );
            Navigator.of(context).pop();
          },
        ),
      );
    });
  }

  @override
  Widget build(BuildContext context) {
    return Consumer<WebSocketService>(
      builder: (context, ws, child) {
        final connected = ws.isConnected;
        final state = _displayState(ws);
        final showWaveform = state == 'listening' || state == 'speaking';
        final waveformColor = state == 'speaking'
            ? AppColors.accentSoft
            : AppColors.accent;
        final a2uiViews = ws.a2uiViews;
        final messages = List<Map<String, dynamic>>.from(ws.messages);

        _syncInputPreview(ws);
        _autoscroll(messages.length);

        return Scaffold(
          body: Container(
            decoration: const BoxDecoration(gradient: AppTheme.appBackground),
            child: Stack(
              children: [
                SafeArea(
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(16, 12, 16, 16),
                    child: Column(
                      children: [
                        _buildHeader(ws, connected, state),
                        const SizedBox(height: 12),
                        Expanded(
                          child: Row(
                            children: [
                              Expanded(
                                child: _buildChatShell(
                                  ws: ws,
                                  connected: connected,
                                  state: state,
                                  showWaveform: showWaveform,
                                  waveformColor: waveformColor,
                                  messages: messages,
                                ),
                              ),
                              if (_showInfoPanel) ...[
                                const SizedBox(width: 12),
                                SizedBox(
                                  width: 360,
                                  child: DashboardPanel(
                                    onClose: () =>
                                        setState(() => _showInfoPanel = false),
                                  ),
                                ),
                              ],
                            ],
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
                A2UIOverlay(
                  views: a2uiViews,
                  onAction: (viewId, actionId, payload, formData) async {
                    await ws.sendA2UIAction(
                      viewId,
                      actionId,
                      payload: payload,
                      form: formData,
                    );
                  },
                ),
              ],
            ),
          ),
        );
      },
    );
  }

  Widget _buildHeader(WebSocketService ws, bool connected, String state) {
    return GlassCard(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      borderRadius: BorderRadius.circular(16),
      child: Row(
        children: [
          Image.asset(
            'assets/branding/Chintu_Header_v2.png',
            height: 28,
            fit: BoxFit.contain,
          ),
          const SizedBox(width: 14),
          _stateChip(state: state, connected: connected),
          const SizedBox(width: 10),
          _metaChip(
            label: ws.lastCapability.isEmpty
                ? 'capability: -'
                : 'capability: ${ws.lastCapability}',
            icon: Icons.memory_rounded,
          ),
          const SizedBox(width: 8),
          _metaChip(
            label: ws.lastModel.isEmpty ? 'model: -' : 'model: ${ws.lastModel}',
            icon: Icons.auto_awesome_rounded,
          ),
          const Spacer(),
          _headerAction(
            icon: _showInfoPanel
                ? Icons.dashboard_rounded
                : Icons.dashboard_outlined,
            tooltip: 'Toggle dashboard',
            selected: _showInfoPanel,
            onTap: () => setState(() => _showInfoPanel = !_showInfoPanel),
          ),
          const SizedBox(width: 6),
          _headerAction(
            icon: Icons.terminal_rounded,
            tooltip: 'Terminal',
            onTap: () => NavRelay.onNavigate?.call(2),
          ),
          const SizedBox(width: 6),
          _headerAction(
            icon: Icons.settings_outlined,
            tooltip: 'Settings',
            onTap: () => Navigator.push(
              context,
              MaterialPageRoute(builder: (_) => const SettingsScreen()),
            ),
          ),
          const SizedBox(width: 6),
          _headerAction(
            icon: Icons.close_rounded,
            tooltip: 'Close',
            onTap: () async => windowManager.close(),
          ),
        ],
      ),
    );
  }

  Widget _buildChatShell({
    required WebSocketService ws,
    required bool connected,
    required String state,
    required bool showWaveform,
    required Color waveformColor,
    required List<Map<String, dynamic>> messages,
  }) {
    return GlassCard(
      borderRadius: BorderRadius.circular(20),
      padding: EdgeInsets.zero,
      child: Column(
        children: [
          Container(
            padding: const EdgeInsets.fromLTRB(16, 14, 16, 12),
            decoration: BoxDecoration(
              color: AppColors.surface.withValues(alpha: 0.42),
              border: Border(
                bottom: BorderSide(
                  color: AppColors.border.withValues(alpha: 0.8),
                ),
              ),
            ),
            child: Row(
              children: [
                SizedBox(
                  width: 66,
                  height: 66,
                  child: showWaveform
                      ? WaveformWidget(
                          audioLevel: ws.audioLevel,
                          isActive: true,
                          color: waveformColor,
                        )
                      : AIOrb(
                          state: state,
                          audioLevel: ws.audioLevel,
                          size: 66,
                        ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        _stateHeadline(state, connected),
                        style: const TextStyle(
                          color: AppColors.textPrimary,
                          fontSize: 14,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                      const SizedBox(height: 3),
                      Text(
                        connected
                            ? 'Speak naturally or type below. Press and hold mic for push-to-talk.'
                            : 'Connecting to backend gateway...',
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          color: AppColors.textMuted,
                          fontSize: 12,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
          Expanded(
            child: messages.isEmpty
                ? _emptyState(connected)
                : _messageList(messages),
          ),
          _buildComposer(ws),
        ],
      ),
    );
  }

  Widget _emptyState(bool connected) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 56,
            height: 56,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: AppColors.surfaceElevated,
              border: Border.all(color: AppColors.borderStrong),
            ),
            child: const Icon(
              Icons.chat_bubble_outline_rounded,
              color: AppColors.textMuted,
              size: 26,
            ),
          ),
          const SizedBox(height: 12),
          Text(
            connected
                ? 'Start with a command or ask a question.'
                : 'Waiting for connection...',
            style: const TextStyle(color: AppColors.textMuted, fontSize: 13),
          ),
        ],
      ),
    );
  }

  Widget _messageList(List<Map<String, dynamic>> messages) {
    return ListView.builder(
      controller: _scrollController,
      padding: const EdgeInsets.all(16),
      itemCount: messages.length,
      itemBuilder: (context, index) {
        final msg = messages[index];
        final isUser = msg['role']?.toString() == 'user';
        final isPartial = msg['isPartial'] == true;
        final timestamp = _formatMessageTime(msg['timestamp']?.toString());

        return Align(
          alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
          child: Container(
            margin: const EdgeInsets.only(bottom: 10),
            constraints: BoxConstraints(
              maxWidth: MediaQuery.of(context).size.width * 0.62,
            ),
            padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
            decoration: BoxDecoration(
              color: isUser
                  ? AppColors.surfaceElevated
                  : AppColors.surfaceStrong,
              borderRadius: BorderRadius.circular(14),
              border: Border.all(
                color: isUser
                    ? AppColors.accent.withValues(alpha: 0.38)
                    : AppColors.border.withValues(alpha: 0.85),
              ),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      isUser ? 'You' : 'Chintu',
                      style: TextStyle(
                        color: isUser
                            ? AppColors.accentSoft
                            : AppColors.textMuted,
                        fontSize: 10.5,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    if (timestamp.isNotEmpty) ...[
                      const SizedBox(width: 8),
                      Text(
                        timestamp,
                        style: const TextStyle(
                          color: AppColors.textMuted,
                          fontSize: 10,
                        ),
                      ),
                    ],
                  ],
                ),
                const SizedBox(height: 6),
                if (isPartial)
                  const Padding(
                    padding: EdgeInsets.only(bottom: 8),
                    child: LinearProgressIndicator(
                      minHeight: 1.5,
                      valueColor: AlwaysStoppedAnimation<Color>(
                        AppColors.accent,
                      ),
                      backgroundColor: AppColors.border,
                    ),
                  ),
                SelectableText(
                  msg['content']?.toString() ?? msg['text']?.toString() ?? '',
                  style: TextStyle(
                    color: AppColors.textPrimary.withValues(
                      alpha: isPartial ? 0.78 : 1,
                    ),
                    fontSize: 13.5,
                    height: 1.45,
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }

  Widget _buildComposer(WebSocketService ws) {
    final hasText = _textController.text.trim().isNotEmpty;

    return Container(
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 12),
      decoration: BoxDecoration(
        color: AppColors.surface.withValues(alpha: 0.44),
        border: Border(
          top: BorderSide(color: AppColors.border.withValues(alpha: 0.75)),
        ),
      ),
      child: Row(
        children: [
          GestureDetector(
            onTapDown: (_) => _startRecording(ws),
            onTapUp: (_) => _stopRecording(ws),
            onTapCancel: () => _stopRecording(ws),
            child: Container(
              width: 44,
              height: 44,
              decoration: BoxDecoration(
                color: _isRecording
                    ? AppColors.accent.withValues(alpha: 0.18)
                    : AppColors.surfaceStrong,
                borderRadius: BorderRadius.circular(22),
                border: Border.all(
                  color: _isRecording
                      ? AppColors.accent
                      : AppColors.borderStrong,
                ),
              ),
              child: Icon(
                _isRecording ? Icons.mic_rounded : Icons.mic_none_rounded,
                color: _isRecording ? AppColors.accent : AppColors.textMuted,
                size: 20,
              ),
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Container(
              height: 44,
              padding: const EdgeInsets.symmetric(horizontal: 14),
              decoration: BoxDecoration(
                color: AppColors.surfaceStrong,
                borderRadius: BorderRadius.circular(22),
                border: Border.all(color: AppColors.border),
              ),
              child: Center(
                child: TextField(
                  controller: _textController,
                  style: const TextStyle(
                    color: AppColors.textPrimary,
                    fontSize: 13.5,
                  ),
                  decoration: const InputDecoration(
                    isDense: true,
                    hintText: 'Ask Chintu...',
                    border: InputBorder.none,
                  ),
                  onChanged: (_) => setState(() {}),
                  onSubmitted: (text) => _sendMessage(ws, text),
                ),
              ),
            ),
          ),
          const SizedBox(width: 10),
          InkWell(
            onTap: hasText
                ? () => _sendMessage(ws, _textController.text)
                : null,
            borderRadius: BorderRadius.circular(22),
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 160),
              width: 44,
              height: 44,
              decoration: BoxDecoration(
                color: hasText ? AppColors.accent : AppColors.surfaceElevated,
                borderRadius: BorderRadius.circular(22),
                border: Border.all(
                  color: hasText
                      ? AppColors.accentSoft
                      : AppColors.borderStrong,
                ),
              ),
              child: Icon(
                Icons.send_rounded,
                color: hasText ? Colors.black : AppColors.textMuted,
                size: 18,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _headerAction({
    required IconData icon,
    required VoidCallback onTap,
    required String tooltip,
    bool selected = false,
  }) {
    final borderColor = selected ? AppColors.accent : AppColors.borderStrong;
    final iconColor = selected ? AppColors.accent : AppColors.textMuted;
    return Tooltip(
      message: tooltip,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(10),
        child: Container(
          width: 34,
          height: 34,
          decoration: BoxDecoration(
            color: AppColors.surfaceStrong.withValues(alpha: 0.92),
            borderRadius: BorderRadius.circular(10),
            border: Border.all(color: borderColor.withValues(alpha: 0.95)),
          ),
          child: Icon(icon, color: iconColor, size: 17),
        ),
      ),
    );
  }

  Widget _stateChip({required String state, required bool connected}) {
    final accent = _stateColor(state, connected);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: accent.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: accent.withValues(alpha: 0.45)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(_stateIcon(state, connected), size: 13, color: accent),
          const SizedBox(width: 6),
          Text(
            _stateLabel(state, connected),
            style: TextStyle(
              color: accent,
              fontSize: 11.5,
              fontWeight: FontWeight.w700,
            ),
          ),
        ],
      ),
    );
  }

  Widget _metaChip({required String label, required IconData icon}) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
      decoration: BoxDecoration(
        color: AppColors.surfaceElevated.withValues(alpha: 0.9),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: AppColors.border),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 12.5, color: AppColors.textMuted),
          const SizedBox(width: 6),
          Text(
            label,
            style: const TextStyle(
              color: AppColors.textMuted,
              fontSize: 10.5,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }

  void _sendMessage(WebSocketService ws, String text) {
    final trimmed = text.trim();
    if (trimmed.isEmpty) return;
    ws.sendCommand(trimmed);
    _textController.clear();
    setState(() {});
  }

  void _startRecording(WebSocketService ws) {
    setState(() => _isRecording = true);
    ws.startPushToTalk();
  }

  void _stopRecording(WebSocketService ws) {
    setState(() => _isRecording = false);
    ws.stopPushToTalk();
  }

  void _autoscroll(int messageCount) {
    if (messageCount == 0) return;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_scrollController.hasClients) return;
      _scrollController.animateTo(
        _scrollController.position.maxScrollExtent,
        duration: const Duration(milliseconds: 180),
        curve: Curves.easeOut,
      );
    });
  }

  void _syncInputPreview(WebSocketService ws) {
    final transcript = ws.transcript;
    if ((ws.status == 'listening' || ws.status == 'processing') &&
        transcript.isNotEmpty) {
      if (_textController.text != transcript) {
        _textController.value = TextEditingValue(
          text: transcript,
          selection: TextSelection.collapsed(offset: transcript.length),
        );
      }
      return;
    }
    if (ws.status == 'idle' &&
        transcript.isNotEmpty &&
        _textController.text == transcript) {
      _textController.clear();
    }
  }

  String _displayState(WebSocketService ws) {
    if (!ws.isConnected) return 'error';
    if (ws.assistantState == 'idle') return 'standby';
    return ws.assistantState;
  }

  String _stateHeadline(String state, bool connected) {
    if (!connected) return 'Offline';
    switch (state) {
      case 'standby':
        return 'Ready for your next task';
      case 'listening':
        return 'Listening';
      case 'processing':
        return 'Thinking';
      case 'speaking':
        return 'Responding';
      default:
        return 'Active';
    }
  }

  String _stateLabel(String state, bool connected) {
    if (!connected) return 'Disconnected';
    switch (state) {
      case 'standby':
        return 'Ready';
      case 'listening':
        return 'Listening';
      case 'processing':
        return 'Thinking';
      case 'speaking':
        return 'Speaking';
      default:
        return 'Active';
    }
  }

  IconData _stateIcon(String state, bool connected) {
    if (!connected) return Icons.error_outline_rounded;
    switch (state) {
      case 'standby':
        return Icons.check_circle_outline_rounded;
      case 'listening':
        return Icons.mic_none_rounded;
      case 'processing':
        return Icons.psychology_outlined;
      case 'speaking':
        return Icons.volume_up_outlined;
      default:
        return Icons.circle_outlined;
    }
  }

  Color _stateColor(String state, bool connected) {
    if (!connected) return AppColors.danger;
    switch (state) {
      case 'standby':
        return AppColors.accent;
      case 'listening':
        return AppColors.accentSoft;
      case 'processing':
        return AppColors.accentDeep;
      case 'speaking':
        return AppColors.accent;
      default:
        return AppColors.textMuted;
    }
  }

  String _formatMessageTime(String? isoTimestamp) {
    if (isoTimestamp == null || isoTimestamp.trim().isEmpty) return '';
    try {
      final dt = DateTime.tryParse(isoTimestamp)?.toLocal();
      if (dt == null) return '';
      final hour = dt.hour.toString().padLeft(2, '0');
      final minute = dt.minute.toString().padLeft(2, '0');
      return '$hour:$minute';
    } catch (_) {
      return '';
    }
  }
}
