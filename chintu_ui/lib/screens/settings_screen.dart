import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/websocket_service.dart';
import '../services/permission_service.dart';
import '../services/logging_service.dart';
import '../theme/app_theme.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  String _serverHost = '127.0.0.1';
  int? _serverPort;
  String _ollamaModel = 'tinyllama';

  @override
  void initState() {
    super.initState();
    logger.log('SettingsScreen', 'Opened settings screen');
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<WebSocketService>().requestWakeWordStatus();
    });
  }

  @override
  Widget build(BuildContext context) {
    return Consumer<PermissionService>(
      builder: (context, permService, child) {
        return Scaffold(
          body: Container(
            decoration: const BoxDecoration(gradient: AppTheme.appBackground),
            child: SafeArea(
              child: Column(
                children: [
                  _buildHeader(),
                  Expanded(
                    child: ListView(
                      padding: const EdgeInsets.all(16),
                      children: [
                        _buildSection('Permissions', [
                          _buildPermissionTile(
                            'Microphone',
                            permService.microphoneGranted ? 'Granted' : 'Required for voice commands',
                            Icons.mic,
                            permService.microphoneGranted,
                            () => _requestMicPermission(permService),
                          ),
                          _buildPermissionTile(
                            'Camera',
                            permService.cameraGranted ? 'Granted' : 'Required for hand gestures',
                            Icons.videocam,
                            permService.cameraGranted,
                            () => _requestCameraPermission(permService),
                          ),
                        ]),
                        const SizedBox(height: 24),
                        _buildSection('Server Connection', [
                          _buildTextField(
                            'Server Host',
                            _serverHost,
                            (v) => setState(() => _serverHost = v),
                          ),
                          _buildTextField(
                            'Server Port',
                            _serverPort?.toString() ?? '',
                            (v) {
                              final trimmed = v.trim();
                              setState(() => _serverPort = trimmed.isEmpty ? null : int.tryParse(trimmed));
                            },
                          ),
                          const SizedBox(height: 8),
                          Text(
                            'Leave port blank to auto-detect the active WebSocket port.',
                            style: TextStyle(color: AppColors.textMuted, fontSize: 12),
                          ),
                          const SizedBox(height: 6),
                          Consumer<WebSocketService>(
                            builder: (context, ws, child) {
                              final mode = ws.usingAutoPort ? 'Auto' : 'Manual';
                              return Text(
                                '$mode endpoint: ${ws.resolvedHost}:${ws.resolvedPort}',
                                style: TextStyle(color: AppColors.textMuted, fontSize: 12),
                              );
                            },
                          ),
                          const SizedBox(height: 16),
                          ElevatedButton.icon(
                            onPressed: _reconnect,
                            icon: const Icon(Icons.refresh),
                            label: const Text('Reconnect'),
                            style: ElevatedButton.styleFrom(
                              backgroundColor: AppColors.accent,
                              foregroundColor: Colors.white,
                              iconColor: Colors.white,
                              padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 24),
                            ),
                          ),
                        ]),
                        const SizedBox(height: 24),
                        _buildSection('LLM Settings', [
                          _buildTextField(
                            'Ollama Model',
                            _ollamaModel,
                            (v) => setState(() => _ollamaModel = v),
                          ),
                          const SizedBox(height: 8),
                          Text(
                            'Available: tinyllama, llama3.2, mistral, codellama, etc.',
                            style: TextStyle(color: AppColors.textMuted, fontSize: 12),
                          ),
                        ]),
                        const SizedBox(height: 24),
                        _buildSection('Wake Word Training', [
                          Text(
                            'Record 5 clear samples of "hey chintu". Tap each number to record.',
                            style: TextStyle(color: AppColors.textMuted, fontSize: 12),
                          ),
                          const SizedBox(height: 6),
                          Text(
                            'When you tap Train, Chintu will also record short background samples. Stay quiet for a few seconds.',
                            style: TextStyle(color: AppColors.textMuted, fontSize: 11),
                          ),
                          const SizedBox(height: 6),
                          Text(
                            'Tips: same mic distance, normal voice, quiet room, pause 0.5s before and after.',
                            style: TextStyle(color: AppColors.textMuted, fontSize: 11),
                          ),
                          const SizedBox(height: 12),
                          Consumer<WebSocketService>(
                            builder: (context, ws, child) {
                              return Column(
                                children: [
                                  Wrap(
                                    spacing: 8,
                                    runSpacing: 8,
                                    children: List.generate(ws.wakeWordSampleCount, (index) {
                                      final sampleIndex = index + 1;
                                      final recorded = index < ws.wakeWordSamples.length
                                          ? ws.wakeWordSamples[index]
                                          : false;
                                      final isRecording = ws.wakeWordRecordingIndex == sampleIndex;
                                      return _buildSampleChip(
                                        sampleIndex,
                                        recorded,
                                        isRecording,
                                        () => ws.recordWakeWordSample(sampleIndex),
                                      );
                                    }),
                                  ),
                                  const SizedBox(height: 16),
                                  Row(
                                    children: [
                                      Expanded(
                                        child: ElevatedButton.icon(
                                          onPressed: ws.requestWakeWordStatus,
                                          icon: const Icon(Icons.sync),
                                          label: const Text('Refresh'),
                                          style: ElevatedButton.styleFrom(
                                            backgroundColor: AppColors.surfaceStrong,
                                            foregroundColor: Colors.white,
                                            iconColor: Colors.white,
                                            padding: const EdgeInsets.symmetric(vertical: 12),
                                          ),
                                        ),
                                      ),
                                      const SizedBox(width: 12),
                                      Expanded(
                                        child: ElevatedButton.icon(
                                          onPressed: (ws.wakeWordSamples.length ==
                                                      ws.wakeWordSampleCount &&
                                                  ws.wakeWordSamples.every((s) => s))
                                              ? ws.trainWakeWord
                                              : null,
                                          icon: const Icon(Icons.fitness_center),
                                          label: const Text('Train Wake Word'),
                                          style: ElevatedButton.styleFrom(
                                            backgroundColor: AppColors.accent,
                                            foregroundColor: Colors.white,
                                            iconColor: Colors.white,
                                            padding: const EdgeInsets.symmetric(vertical: 12),
                                          ),
                                        ),
                                      ),
                                    ],
                                  ),
                                  if (ws.wakeWordTrainingStatus.isNotEmpty) ...[
                                    const SizedBox(height: 12),
                                    Text(
                                      ws.wakeWordTrainingMessage.isNotEmpty
                                          ? ws.wakeWordTrainingMessage
                                          : ws.wakeWordTrainingStatus,
                                      style: TextStyle(color: AppColors.textMuted, fontSize: 12),
                                    ),
                                  ],
                                ],
                              );
                            },
                          ),
                        ]),
                        const SizedBox(height: 24),
                        _buildSection('About', [
                          ListTile(
                            title: const Text('Chintu AI Assistant', style: TextStyle(color: Colors.white)),
                            subtitle: Text('Version 1.0.0', style: TextStyle(color: AppColors.textMuted)),
                            leading: Container(
                              width: 48,
                              height: 48,
                              decoration: BoxDecoration(
                                color: AppColors.surfaceStrong.withValues(alpha: 0.7),
                                borderRadius: BorderRadius.circular(12),
                                border: Border.all(color: AppColors.border.withValues(alpha: 0.8)),
                              ),
                              child: ClipRRect(
                                borderRadius: BorderRadius.circular(10),
                                child: Image.asset('assets/branding/Chintu_Mark.png', fit: BoxFit.contain),
                              ),
                            ),
                          ),
                        ]),
                      ],
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

  Widget _buildHeader() {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      child: Row(
        children: [
          IconButton(
            onPressed: () => Navigator.pop(context),
            icon: const Icon(Icons.arrow_back, color: AppColors.textPrimary),
          ),
          const SizedBox(width: 4),
          Container(
            width: 36,
            height: 36,
            decoration: BoxDecoration(
              color: AppColors.surfaceStrong.withValues(alpha: 0.7),
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: AppColors.border.withValues(alpha: 0.8)),
            ),
            child: ClipRRect(
              borderRadius: BorderRadius.circular(8),
              child: Image.asset('assets/branding/Chintu_Mark.png', fit: BoxFit.contain),
            ),
          ),
          const SizedBox(width: 12),
          Text(
            'Settings',
            style: const TextStyle(
              color: AppColors.textPrimary,
              fontSize: 22,
              fontWeight: FontWeight.w600,
              letterSpacing: 0.4,
            ),
          ),
          const Spacer(),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: AppColors.border.withValues(alpha: 0.35)),
              boxShadow: [
                BoxShadow(
                  color: AppColors.accentDeep.withValues(alpha: 0.16),
                  blurRadius: 12,
                  offset: const Offset(0, 6),
                ),
              ],
            ),
            child: Image.asset(
              'assets/branding/Chintu_Wordmark.png',
              height: 18,
              fit: BoxFit.contain,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildSection(String title, List<Widget> children) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          title,
          style: const TextStyle(
            color: AppColors.accent,
            fontSize: 18,
            fontWeight: FontWeight.bold,
          ),
        ),
        const SizedBox(height: 12),
        Container(
          decoration: BoxDecoration(
            color: AppColors.surface.withValues(alpha: 0.85),
            borderRadius: BorderRadius.circular(16),
            border: Border.all(color: AppColors.border.withValues(alpha: 0.7)),
            boxShadow: [
              BoxShadow(
                color: AppColors.accentDeep.withValues(alpha: 0.18),
                blurRadius: 20,
                offset: const Offset(0, 10),
              ),
            ],
          ),
          padding: const EdgeInsets.all(16),
          child: Column(children: children),
        ),
      ],
    );
  }

  Widget _buildPermissionTile(String title, String subtitle, IconData icon, bool enabled, VoidCallback onTap) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(12),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 8),
        child: LayoutBuilder(
          builder: (context, constraints) {
            final isCompact = constraints.maxWidth < 360;
            final iconWidget = Icon(icon, color: enabled ? AppColors.success : AppColors.textMuted);
            final switchWidget = Switch(
              value: enabled,
              onChanged: (_) => onTap(),
              activeTrackColor: AppColors.accent,
              activeThumbColor: Colors.white,
              materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
            );

            if (isCompact) {
              return Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      iconWidget,
                      const SizedBox(width: 12),
                      Expanded(
                        child: Text(title, style: const TextStyle(color: Colors.white)),
                      ),
                    ],
                  ),
                  const SizedBox(height: 6),
                  Text(subtitle, style: TextStyle(color: AppColors.textMuted)),
                  const SizedBox(height: 8),
                  Align(
                    alignment: Alignment.centerRight,
                    child: switchWidget,
                  ),
                ],
              );
            }

            return Row(
              children: [
                iconWidget,
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(title, style: const TextStyle(color: Colors.white)),
                      const SizedBox(height: 2),
                      Text(subtitle, style: TextStyle(color: AppColors.textMuted)),
                    ],
                  ),
                ),
                switchWidget,
              ],
            );
          },
        ),
      ),
    );
  }

  Future<void> _requestMicPermission(PermissionService permService) async {
    logger.log('SettingsScreen', 'Requesting microphone permission');
    final granted = await permService.requestMicrophone();

    if (!granted && mounted) {
      _showPermissionHelp('Microphone', 'microphone', permService);
    }
  }

  Future<void> _requestCameraPermission(PermissionService permService) async {
    logger.log('SettingsScreen', 'Requesting camera permission');
    final granted = await permService.requestCamera();

    if (!granted && mounted) {
      _showPermissionHelp('Camera', 'camera', permService);
    }
  }

  void _showPermissionHelp(String name, String type, PermissionService permService) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppColors.surface,
        title: Text('Enable $name', style: const TextStyle(color: Colors.white)),
        content: Text(
          '''Permission was denied. To enable $type:

1. Open Windows Settings
2. Go to Privacy & Security > $name
3. Enable "Let desktop apps access your $type"

Or click "Open Settings" below.''',
          style: const TextStyle(color: Colors.white70),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Cancel', style: TextStyle(color: AppColors.textMuted)),
          ),
          ElevatedButton(
            onPressed: () {
              Navigator.pop(ctx);
              permService.openSettings();
            },
            style: ElevatedButton.styleFrom(
              backgroundColor: AppColors.accent,
              foregroundColor: Colors.white,
            ),
            child: const Text('Open Settings', style: TextStyle(color: Colors.white)),
          ),
        ],
      ),
    );
  }

  void _reconnect() {
    final ws = context.read<WebSocketService>();
    ws.connect(host: _serverHost, port: _serverPort);
    final portLabel = _serverPort == null ? 'auto' : _serverPort.toString();
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text('Reconnecting to $_serverHost:$portLabel...'),
        backgroundColor: AppColors.accent,
      ),
    );
  }

  Widget _buildTextField(String label, String value, Function(String) onChanged) {
    return TextField(
      controller: TextEditingController(text: value),
      onChanged: onChanged,
      style: const TextStyle(color: Colors.white),
      decoration: InputDecoration(
        labelText: label,
        labelStyle: TextStyle(color: AppColors.textMuted),
        enabledBorder: OutlineInputBorder(
          borderSide: BorderSide(color: AppColors.border),
          borderRadius: BorderRadius.circular(8),
        ),
        focusedBorder: OutlineInputBorder(
          borderSide: const BorderSide(color: AppColors.accent),
          borderRadius: BorderRadius.circular(8),
        ),
      ),
    );
  }

  Widget _buildSampleChip(
    int index,
    bool recorded,
    bool isRecording,
    VoidCallback onTap,
  ) {
    final color = recorded ? AppColors.success : AppColors.textMuted;
    final label = isRecording ? 'Recording...' : 'Sample $index';
    return SizedBox(
      width: 120,
      child: OutlinedButton(
        onPressed: isRecording ? null : onTap,
        style: OutlinedButton.styleFrom(
          side: BorderSide(color: color.withValues(alpha: 0.6)),
          backgroundColor: recorded ? color.withValues(alpha: 0.1) : null,
        ),
        child: Column(
          children: [
            Text(
              label,
              style: TextStyle(
                color: recorded ? Colors.white : AppColors.textMuted,
                fontSize: 12,
              ),
            ),
            const SizedBox(height: 4),
            Text(
              recorded ? 'Recorded' : 'Tap to record',
              style: TextStyle(
                color: recorded ? AppColors.success : AppColors.textMuted,
                fontSize: 10,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
