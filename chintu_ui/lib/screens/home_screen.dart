import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:window_manager/window_manager.dart';
import '../main.dart';
import '../services/websocket_service.dart';
import '../widgets/ai_orb.dart';
import '../widgets/waveform_widget.dart';
import '../widgets/glass_card.dart';
import '../widgets/system_health_panel.dart';
import '../widgets/scheduled_tasks_panel.dart';
import '../widgets/activity_log_panel.dart';
import '../widgets/hud_panel.dart';
import '../widgets/code_approval_dialog.dart';
import '../widgets/a2ui_overlay.dart';
import '../widgets/background_grid.dart';
import '../theme/app_theme.dart';
import 'settings_screen.dart';
import '../widgets/backend_log_panel.dart';
import 'dart:async';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});
  @override State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final TextEditingController _textController = TextEditingController();
  final ScrollController _scrollController = ScrollController();
  bool _isRecording = false;
  bool _showBackendLogs = false;
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

    // Give the A2UI path a moment to render; if present, skip this fallback dialog.
    Future.delayed(const Duration(milliseconds: 150), () {
      if (!mounted) return;
      final ws = context.read<WebSocketService>();
      if (ws.hasA2UIView(category: 'code_approval') || ws.hasA2UIView(kind: 'code_approval')) {
        return;
      }

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
    });
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
        final a2uiViews = ws.a2uiViews;
        final hud = ws.hud;
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
                                    hud,
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
                                    hud,
                                    displayMessages,
                                  ),
                          ),
                        ],
                      );
                    },
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

  Widget _buildBackdrop() {
    return const Stack(
      children: [
        Positioned.fill(
          child: IgnorePointer(
            child: BackgroundGrid(spacing: 80, lineOpacity: 0.03),
          ),
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
              Row(
                children: [
                  Container(
                    width: 38,
                    height: 38,
                    padding: const EdgeInsets.all(6),
                    decoration: BoxDecoration(
                      color: AppColors.surface,
                      shape: BoxShape.circle,
                      border: Border.all(color: AppColors.accent.withValues(alpha: 0.3)),
                      boxShadow: [
                        BoxShadow(
                          color: AppColors.accent.withValues(alpha: 0.1),
                          blurRadius: 10,
                          spreadRadius: 2,
                        ),
                      ],
                    ),
                    child: Image.asset(
                      'assets/branding/Chintu_Mark.png',
                      fit: BoxFit.contain,
                      color: Colors.white,
                    ),
                  ),
                  const SizedBox(width: 12),
                  Text(
                    'CHINTU',
                    style: theme.textTheme.headlineMedium?.copyWith(
                      fontSize: 18,
                      letterSpacing: 2.0,
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                ],
              ),
            ],
          ),
          const Spacer(),
          _buildStatusChip(displayState, connected),
          const SizedBox(width: 12),
          _buildConnectionStatus(connected),
          const SizedBox(width: 12),
          _buildWindowButton(Icons.terminal, () => NavRelay.onNavigate?.call(2)),
          const SizedBox(width: 12),
          _buildWindowButton(Icons.settings, () => Navigator.push(context, MaterialPageRoute(builder: (_) => const SettingsScreen()))),
          const SizedBox(width: 8),
          _buildWindowButton(Icons.close, () async => await windowManager.close()),
        ],
      ),
    );
  }

  Widget _buildLeftRail(
    ThemeData theme,
    List<Map<String, dynamic>> capabilities,
    Map<String, dynamic> hud,
  ) {
    return Column(
      children: [
        Expanded(
          flex: 4,
          child: _buildSectionCard(
            title: 'Systems',
            icon: Icons.sensors,
            child: SystemHealthPanel(capabilities: capabilities),
            bodyPadding: EdgeInsets.zero,
          ),
        ),
        const SizedBox(height: 16),
        Expanded(
          flex: 3,
          child: _buildSectionCard(
            title: 'Schedules',
            icon: Icons.event_available,
            child: const ScheduledTasksPanel(),
            bodyPadding: const EdgeInsets.fromLTRB(8, 6, 8, 12),
          ),
        ),
        const SizedBox(height: 16),
        Expanded(
          flex: 3,
          child: _buildSectionCard(
            title: 'Neural HUD',
            icon: Icons.hub,
            child: HudPanel(hud: hud),
            bodyPadding: const EdgeInsets.fromLTRB(10, 4, 10, 12),
          ),
        ),
      ],
    );
  }

  Widget _buildRightRail(
    ThemeData theme,
    bool connected,
    List<Map<String, dynamic>> displayMessages,
  ) {
    return Column(
      children: [
        Expanded(
          flex: 6,
          child: _buildConversationPanel(theme, connected, displayMessages),
        ),
        const SizedBox(height: 16),
        Expanded(
          flex: 4,
          child: _buildSectionCard(
            title: _showBackendLogs ? 'System Logs' : 'Activity',
            icon: _showBackendLogs ? Icons.terminal : Icons.track_changes,
            trailing: IconButton(
              icon: Icon(
                _showBackendLogs ? Icons.visibility : Icons.terminal,
                size: 16,
                color: AppColors.accent.withValues(alpha: 0.7),
              ),
              onPressed: () => setState(() => _showBackendLogs = !_showBackendLogs),
              tooltip: _showBackendLogs ? 'Show activity' : 'Show terminal',
            ),
            child: _showBackendLogs ? const BackendLogPanel() : const ActivityLogPanel(),
            bodyPadding: _showBackendLogs ? EdgeInsets.zero : const EdgeInsets.fromLTRB(10, 4, 10, 12),
          ),
        ),
      ],
    );
  }

  Widget _buildSectionCard({
    required String title,
    required IconData icon,
    required Widget child,
    Widget? trailing,
    EdgeInsets? bodyPadding,
  }) {
    return GlassCard(
      padding: EdgeInsets.zero,
      borderRadius: BorderRadius.circular(22),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 14, 14, 10),
            child: Row(
              children: [
                Container(
                  width: 28,
                  height: 28,
                  decoration: BoxDecoration(
                    color: AppColors.accent.withValues(alpha: 0.12),
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(color: AppColors.accent.withValues(alpha: 0.25)),
                  ),
                  child: Icon(icon, size: 15, color: AppColors.accent),
                ),
                const SizedBox(width: 10),
                Text(title, style: const TextStyle(color: AppColors.textPrimary, fontWeight: FontWeight.w600, fontSize: 15)),
                const Spacer(),
                if (trailing != null) trailing,
              ],
            ),
          ),
          Container(
            height: 1,
            color: AppColors.border.withValues(alpha: 0.6),
            margin: const EdgeInsets.symmetric(horizontal: 16),
          ),
          Expanded(
            child: Padding(
              padding: bodyPadding ?? const EdgeInsets.fromLTRB(12, 8, 12, 12),
              child: child,
            ),
          ),
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
    Map<String, dynamic> hud,
    List<Map<String, dynamic>> displayMessages,
  ) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 10, 16, 16),
      child: Row(
        children: [
          SizedBox(
            width: 300,
            child: _buildLeftRail(
              theme,
              capabilities,
              hud,
            ),
          ),
          const SizedBox(width: 18),
          Expanded(
            flex: 2,
            child: _buildCenterStage(
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
            child: _buildRightRail(
              theme,
              connected,
              displayMessages,
            ),
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
    Map<String, dynamic> hud,
    List<Map<String, dynamic>> displayMessages,
  ) {
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(16, 10, 16, 16),
      child: Column(
        children: [
          _buildCenterStage(
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
          _buildSectionCard(
            title: 'Systems',
            icon: Icons.sensors,
            child: SystemHealthPanel(capabilities: capabilities),
          ),
          const SizedBox(height: 16),
          _buildSectionCard(
            title: 'Schedules',
            icon: Icons.event_available,
            child: const ScheduledTasksPanel(),
          ),
          const SizedBox(height: 16),
          _buildSectionCard(
            title: 'Neural HUD',
            icon: Icons.hub,
            child: HudPanel(hud: hud),
          ),
          const SizedBox(height: 16),
          _buildSectionCard(
            title: _showBackendLogs ? 'System Logs' : 'Activity',
            icon: _showBackendLogs ? Icons.terminal : Icons.track_changes,
            trailing: IconButton(
              icon: Icon(
                _showBackendLogs ? Icons.visibility : Icons.terminal,
                size: 16,
                color: AppColors.accent.withValues(alpha: 0.7),
              ),
              onPressed: () => setState(() => _showBackendLogs = !_showBackendLogs),
            ),
            child: _showBackendLogs ? const BackendLogPanel() : const ActivityLogPanel(),
            bodyPadding: _showBackendLogs ? EdgeInsets.zero : const EdgeInsets.fromLTRB(10, 4, 10, 12),
          ),
        ],
      ),
    );
  }

  Widget _buildCenterStage(
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
      padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 22),
      borderRadius: BorderRadius.circular(26),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.blur_on, color: AppColors.accent, size: 18),
              const SizedBox(width: 10),
              Text('Command Center', style: theme.textTheme.titleLarge),
              const Spacer(),
              _buildStatusChip(displayState, connected),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            connected ? 'System active' : 'Connecting to core...',
            style: theme.textTheme.bodySmall?.copyWith(color: AppColors.textMuted, letterSpacing: 1.1),
          ),
          const SizedBox(height: 18),
          Expanded(
            child: Center(
              child: showWaveform
                  ? SizedBox(
                      height: 240,
                      child: WaveformWidget(
                        audioLevel: waveformLevel,
                        isActive: waveformActive,
                        color: waveformColor,
                      ),
                    )
                  : AIOrb(state: displayState, audioLevel: audioLevel, size: 240),
            ),
          ),
          const SizedBox(height: 16),
          Center(child: StateIndicator(state: displayState)),
          const SizedBox(height: 10),
          _buildHintRow(displayState, connected),
          const SizedBox(height: 16),
          _buildQuickActions(theme),
        ],
      ),
    );
  }

  Widget _buildConversationPanel(ThemeData theme, bool connected, List<Map<String, dynamic>> displayMessages) {
    return GlassCard(
      padding: EdgeInsets.zero,
      borderRadius: BorderRadius.circular(24),
      child: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 14, 14, 10),
            child: Row(
              children: [
                Container(
                  width: 28,
                  height: 28,
                  decoration: BoxDecoration(
                    color: AppColors.accent.withValues(alpha: 0.12),
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(color: AppColors.accent.withValues(alpha: 0.25)),
                  ),
                  child: const Icon(Icons.chat_bubble_outline, color: AppColors.accent, size: 15),
                ),
                const SizedBox(width: 10),
                Text('Conversation', style: theme.textTheme.titleLarge),
                const Spacer(),
                _buildConnectionStatus(connected),
              ],
            ),
          ),
          Container(
            height: 1,
            color: AppColors.border.withValues(alpha: 0.6),
            margin: const EdgeInsets.symmetric(horizontal: 16),
          ),
          Expanded(
            child: displayMessages.isEmpty
                ? Center(
                    child: Text(
                      connected ? 'Say "Hey Chintu" or type a command to begin.' : 'Waiting for backend...',
                      style: theme.textTheme.bodySmall,
                      textAlign: TextAlign.center,
                    ),
                  )
                : ListView.builder(
                    controller: _scrollController,
                    padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
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
      padding: const EdgeInsets.fromLTRB(14, 10, 14, 12),
      decoration: BoxDecoration(
        color: AppColors.surfaceElevated.withValues(alpha: 0.6),
        border: Border(top: BorderSide(color: AppColors.border.withValues(alpha: 0.6))),
      ),
      child: Row(
        children: [
          GestureDetector(
            onTapDown: (_) => _startRecording(context.read<WebSocketService>()),
            onTapUp: (_) => _stopRecording(context.read<WebSocketService>()),
            onTapCancel: () => _stopRecording(context.read<WebSocketService>()),
            child: Container(
              width: 44,
              height: 44,
              margin: const EdgeInsets.only(right: 10),
              decoration: BoxDecoration(
                color: _isRecording
                    ? AppColors.accent.withValues(alpha: 0.2)
                    : AppColors.surfaceStrong.withValues(alpha: 0.6),
                borderRadius: BorderRadius.circular(22),
                border: Border.all(
                  color: _isRecording
                      ? AppColors.accent
                      : AppColors.border.withValues(alpha: 0.6),
                  width: _isRecording ? 1.5 : 1.0,
                ),
              ),
              child: Icon(
                _isRecording ? Icons.mic : Icons.mic_none,
                color: _isRecording ? AppColors.accent : AppColors.textMuted,
                size: 20,
              ),
            ),
          ),
          Expanded(
            child: Container(
              height: 42,
              padding: const EdgeInsets.symmetric(horizontal: 12),
              decoration: BoxDecoration(
                color: AppColors.surfaceStrong.withValues(alpha: 0.6),
                borderRadius: BorderRadius.circular(14),
                border: Border.all(color: AppColors.border.withValues(alpha: 0.6)),
              ),
              child: Center(
                child: TextField(
                  controller: _textController,
                  style: theme.textTheme.bodyMedium,
                  decoration: InputDecoration(
                    hintText: 'Type a command or ask anything...',
                    hintStyle: theme.textTheme.bodySmall,
                    border: InputBorder.none,
                  ),
                  onSubmitted: (text) => _sendMessage(context.read<WebSocketService>(), text),
                ),
              ),
            ),
          ),
          const SizedBox(width: 10),
          InkWell(
            onTap: () => _sendMessage(context.read<WebSocketService>(), _textController.text),
            borderRadius: BorderRadius.circular(14),
            child: Container(
              width: 44,
              height: 44,
              decoration: BoxDecoration(
                color: AppColors.accent.withValues(alpha: 0.2),
                borderRadius: BorderRadius.circular(14),
                border: Border.all(color: AppColors.accent.withValues(alpha: 0.5)),
              ),
              child: const Icon(Icons.arrow_upward, color: AppColors.accent, size: 18),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildStatusChip(String displayState, bool connected) {
    final Map<String, Color> colors = {
      'standby': AppColors.accent,
      'listening': AppColors.accentSoft,
      'processing': AppColors.accentDeep,
      'speaking': AppColors.accentSoft,
      'error': AppColors.accentDeep,
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

  Widget _buildQuickActions(ThemeData theme) {
    final actions = [
      {'label': 'Daily brief', 'command': 'Give me a 2-minute daily briefing', 'icon': Icons.today},
      {'label': 'Summarize', 'command': 'Summarize my clipboard', 'icon': Icons.article},
      {'label': 'New task', 'command': 'Create a new task', 'icon': Icons.check_circle_outline},
      {'label': 'Open app', 'command': 'Open Visual Studio Code', 'icon': Icons.apps},
      {'label': 'Search web', 'command': 'Research the latest on AI productivity', 'icon': Icons.search},
    ];

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('Quick Actions', style: theme.textTheme.labelLarge),
        const SizedBox(height: 8),
        Wrap(
          spacing: 10,
          runSpacing: 10,
          children: actions.map((action) {
            return InkWell(
              borderRadius: BorderRadius.circular(14),
              onTap: () => _sendMessage(context.read<WebSocketService>(), action['command'] as String),
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                decoration: BoxDecoration(
                  color: AppColors.surfaceStrong.withValues(alpha: 0.45),
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(color: AppColors.border.withValues(alpha: 0.6)),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(action['icon'] as IconData, size: 16, color: AppColors.accent),
                    const SizedBox(width: 8),
                    Text(
                      action['label'] as String,
                      style: const TextStyle(color: AppColors.textPrimary, fontSize: 12, fontWeight: FontWeight.w600),
                    ),
                  ],
                ),
              ),
            );
          }).toList(),
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
            color: connected ? AppColors.accent : AppColors.accentDeep,
            boxShadow: [
              BoxShadow(
                color: (connected ? AppColors.accent : AppColors.accentDeep).withValues(alpha: 0.5),
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
        ? AppColors.surfaceElevated
        : (isSystem ? AppColors.danger.withValues(alpha: 0.08) : Colors.transparent);
    final borderColor = isUser
        ? AppColors.accent.withValues(alpha: 0.4)
        : (isSystem ? AppColors.danger.withValues(alpha: 0.3) : Colors.transparent);

    return Align(
      alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.only(bottom: 12),
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.75),
        decoration: BoxDecoration(
          color: bubbleColor,
          borderRadius: BorderRadius.circular(16),
          border: isUser || isSystem ? Border.all(color: borderColor) : null,
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
