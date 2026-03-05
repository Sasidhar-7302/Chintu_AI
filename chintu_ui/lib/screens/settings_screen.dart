import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../services/logging_service.dart';
import '../services/permission_service.dart';
import '../services/stealth_window_service.dart';
import '../services/websocket_service.dart';
import '../theme/app_theme.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final TextEditingController _serverHostController = TextEditingController(
    text: '127.0.0.1',
  );
  final TextEditingController _serverPortController = TextEditingController();
  final TextEditingController _ollamaModelController = TextEditingController(
    text: 'tinyllama',
  );

  bool _stealthMode = true;
  bool _stealthSupported = false;
  bool _stealthBusy = false;

  @override
  void initState() {
    super.initState();
    logger.log('SettingsScreen', 'Opened settings');
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<WebSocketService>().requestWakeWordStatus();
    });
    StealthWindowService.isSupported().then((supported) {
      if (!mounted) return;
      setState(() => _stealthSupported = supported);
    });
  }

  @override
  void dispose() {
    _serverHostController.dispose();
    _serverPortController.dispose();
    _ollamaModelController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Consumer2<WebSocketService, PermissionService>(
      builder: (context, ws, perms, child) {
        return Scaffold(
          body: Container(
            decoration: const BoxDecoration(gradient: AppTheme.appBackground),
            child: SafeArea(
              child: Column(
                children: [
                  _buildHeader(),
                  Expanded(
                    child: ListView(
                      padding: const EdgeInsets.fromLTRB(16, 6, 16, 18),
                      children: [
                        _buildAccessCard(perms),
                        const SizedBox(height: 12),
                        _buildConnectionCard(ws),
                        const SizedBox(height: 12),
                        _buildModelCard(),
                        const SizedBox(height: 12),
                        _buildWakeWordCard(ws),
                        if (_stealthSupported) ...[
                          const SizedBox(height: 12),
                          _buildPrivacyCard(),
                        ],
                        const SizedBox(height: 12),
                        _buildAboutCard(),
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
      padding: const EdgeInsets.fromLTRB(10, 8, 12, 8),
      child: Row(
        children: [
          IconButton(
            onPressed: () => Navigator.pop(context),
            icon: const Icon(
              Icons.arrow_back_rounded,
              color: AppColors.textPrimary,
            ),
          ),
          const SizedBox(width: 4),
          const Text(
            'Settings',
            style: TextStyle(
              color: AppColors.textPrimary,
              fontSize: 22,
              fontWeight: FontWeight.w700,
            ),
          ),
          const Spacer(),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
            decoration: BoxDecoration(
              color: AppColors.surfaceStrong,
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: AppColors.border),
            ),
            child: const Text(
              'System Controls',
              style: TextStyle(
                color: AppColors.textMuted,
                fontSize: 11,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildAccessCard(PermissionService perms) {
    return _settingsCard(
      title: 'Access',
      subtitle: 'Required permissions for voice and camera capabilities.',
      child: Column(
        children: [
          _permissionRow(
            icon: Icons.mic_none_rounded,
            title: 'Microphone',
            status: perms.microphoneGranted ? 'Granted' : 'Not granted',
            active: perms.microphoneGranted,
            onTap: () => _requestMicPermission(perms),
          ),
          const SizedBox(height: 8),
          _permissionRow(
            icon: Icons.videocam_outlined,
            title: 'Camera',
            status: perms.cameraGranted ? 'Granted' : 'Not granted',
            active: perms.cameraGranted,
            onTap: () => _requestCameraPermission(perms),
          ),
        ],
      ),
    );
  }

  Widget _buildConnectionCard(WebSocketService ws) {
    if (ws.resolvedHost.isNotEmpty &&
        _serverHostController.text.trim() != ws.resolvedHost) {
      _serverHostController.text = ws.resolvedHost;
    }
    if (!ws.usingAutoPort &&
        _serverPortController.text.trim() != ws.resolvedPort.toString()) {
      _serverPortController.text = ws.resolvedPort.toString();
    }

    return _settingsCard(
      title: 'Gateway',
      subtitle:
          'Configure backend endpoint. Leave port empty for auto-discovery.',
      child: Column(
        children: [
          TextField(
            controller: _serverHostController,
            decoration: const InputDecoration(
              labelText: 'Host',
              hintText: '127.0.0.1',
            ),
          ),
          const SizedBox(height: 10),
          TextField(
            controller: _serverPortController,
            keyboardType: TextInputType.number,
            decoration: const InputDecoration(
              labelText: 'Port (optional)',
              hintText: 'Auto',
            ),
          ),
          const SizedBox(height: 10),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
            decoration: BoxDecoration(
              color: AppColors.surfaceElevated,
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: AppColors.border),
            ),
            child: Text(
              '${ws.usingAutoPort ? "Auto" : "Manual"} endpoint: ${ws.resolvedHost}:${ws.resolvedPort}',
              style: const TextStyle(
                color: AppColors.textMuted,
                fontSize: 12,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
          const SizedBox(height: 12),
          Align(
            alignment: Alignment.centerLeft,
            child: ElevatedButton.icon(
              onPressed: _reconnect,
              icon: const Icon(Icons.refresh_rounded),
              label: const Text('Reconnect'),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildModelCard() {
    return _settingsCard(
      title: 'Model Defaults',
      subtitle:
          'Used when explicit model routing is not provided by a task contract.',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          TextField(
            controller: _ollamaModelController,
            decoration: const InputDecoration(
              labelText: 'Local Ollama model',
              hintText: 'tinyllama / qwen2.5:3b / llama3.1:8b',
            ),
          ),
          const SizedBox(height: 8),
          const Text(
            'Tip: keep a lightweight local model for routine prompts and reserve larger models for complex reasoning.',
            style: TextStyle(color: AppColors.textMuted, fontSize: 11.5),
          ),
        ],
      ),
    );
  }

  Widget _buildWakeWordCard(WebSocketService ws) {
    return _settingsCard(
      title: 'Wake Word',
      subtitle: 'Record 5 samples of "hey chintu" and train detection.',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
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
              return _sampleChip(
                index: sampleIndex,
                recorded: recorded,
                recording: isRecording,
                onTap: () => ws.recordWakeWordSample(sampleIndex),
              );
            }),
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: ws.requestWakeWordStatus,
                  icon: const Icon(Icons.sync_rounded, size: 18),
                  label: const Text('Refresh'),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: ElevatedButton.icon(
                  onPressed:
                      (ws.wakeWordSamples.length == ws.wakeWordSampleCount &&
                          ws.wakeWordSamples.every((s) => s))
                      ? ws.trainWakeWord
                      : null,
                  icon: const Icon(Icons.fitness_center_rounded, size: 18),
                  label: const Text('Train'),
                ),
              ),
            ],
          ),
          if (ws.wakeWordTrainingStatus.isNotEmpty) ...[
            const SizedBox(height: 10),
            Text(
              ws.wakeWordTrainingMessage.isNotEmpty
                  ? ws.wakeWordTrainingMessage
                  : ws.wakeWordTrainingStatus,
              style: const TextStyle(color: AppColors.textMuted, fontSize: 12),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildPrivacyCard() {
    return _settingsCard(
      title: 'Privacy',
      subtitle:
          'Stealth mode hides the app in most desktop-capture flows on Windows.',
      child: Row(
        children: [
          const Expanded(
            child: Text(
              'Stealth Mode',
              style: TextStyle(
                color: AppColors.textPrimary,
                fontSize: 14,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
          Switch(
            value: _stealthMode,
            onChanged: _stealthBusy ? null : _setStealthMode,
            activeTrackColor: AppColors.accent.withValues(alpha: 0.45),
            activeThumbColor: AppColors.accent,
          ),
        ],
      ),
    );
  }

  Widget _buildAboutCard() {
    return _settingsCard(
      title: 'About',
      subtitle: 'Current app profile and branding.',
      child: Row(
        children: [
          Container(
            width: 44,
            height: 44,
            decoration: BoxDecoration(
              color: AppColors.surfaceElevated,
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: AppColors.border),
            ),
            child: ClipRRect(
              borderRadius: BorderRadius.circular(8),
              child: Image.asset(
                'assets/branding/ChintuLogo.png',
                fit: BoxFit.contain,
              ),
            ),
          ),
          const SizedBox(width: 12),
          const Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Chintu AI Assistant',
                style: TextStyle(
                  color: AppColors.textPrimary,
                  fontSize: 14,
                  fontWeight: FontWeight.w700,
                ),
              ),
              SizedBox(height: 3),
              Text(
                'Version 1.0.0',
                style: TextStyle(color: AppColors.textMuted, fontSize: 12),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _settingsCard({
    required String title,
    required String subtitle,
    required Widget child,
  }) {
    return Container(
      decoration: BoxDecoration(
        color: AppColors.surface.withValues(alpha: 0.94),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppColors.border),
      ),
      padding: const EdgeInsets.all(14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: const TextStyle(
              color: AppColors.textPrimary,
              fontSize: 15,
              fontWeight: FontWeight.w700,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            subtitle,
            style: const TextStyle(color: AppColors.textMuted, fontSize: 12),
          ),
          const SizedBox(height: 12),
          child,
        ],
      ),
    );
  }

  Widget _permissionRow({
    required IconData icon,
    required String title,
    required String status,
    required bool active,
    required VoidCallback onTap,
  }) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: AppColors.surfaceStrong,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: active
              ? AppColors.accent.withValues(alpha: 0.45)
              : AppColors.borderStrong,
        ),
      ),
      child: Row(
        children: [
          Icon(
            icon,
            color: active ? AppColors.accent : AppColors.textMuted,
            size: 20,
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: const TextStyle(
                    color: AppColors.textPrimary,
                    fontSize: 13.5,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  status,
                  style: TextStyle(
                    color: active ? AppColors.accentSoft : AppColors.textMuted,
                    fontSize: 11.5,
                  ),
                ),
              ],
            ),
          ),
          OutlinedButton(
            onPressed: onTap,
            child: Text(active ? 'Review' : 'Enable'),
          ),
        ],
      ),
    );
  }

  Widget _sampleChip({
    required int index,
    required bool recorded,
    required bool recording,
    required VoidCallback onTap,
  }) {
    return SizedBox(
      width: 118,
      child: OutlinedButton(
        onPressed: recording ? null : onTap,
        style: OutlinedButton.styleFrom(
          backgroundColor: recorded
              ? AppColors.accent.withValues(alpha: 0.12)
              : null,
          side: BorderSide(
            color: recorded
                ? AppColors.accent.withValues(alpha: 0.6)
                : AppColors.borderStrong,
          ),
        ),
        child: Column(
          children: [
            Text(
              recording ? 'Recording' : 'Sample $index',
              style: const TextStyle(
                color: AppColors.textPrimary,
                fontSize: 12,
                fontWeight: FontWeight.w600,
              ),
            ),
            const SizedBox(height: 4),
            Text(
              recording ? '...' : (recorded ? 'Recorded' : 'Tap to record'),
              style: TextStyle(
                color: recorded ? AppColors.accentSoft : AppColors.textMuted,
                fontSize: 10.5,
              ),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _setStealthMode(bool enabled) async {
    setState(() => _stealthBusy = true);
    final ok = await StealthWindowService.setStealthMode(enabled);
    if (!mounted) return;
    setState(() => _stealthBusy = false);
    if (!ok) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Stealth mode not supported on this system.'),
        ),
      );
      return;
    }
    setState(() => _stealthMode = enabled);
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

  void _showPermissionHelp(
    String name,
    String type,
    PermissionService permService,
  ) {
    showDialog<void>(
      context: context,
      builder: (ctx) {
        return AlertDialog(
          backgroundColor: AppColors.surface,
          title: Text(
            'Enable $name',
            style: const TextStyle(color: AppColors.textPrimary),
          ),
          content: Text(
            'Permission is blocked.\n\n'
            '1) Open Windows Settings\n'
            '2) Go to Privacy & Security > $name\n'
            '3) Enable desktop app access for $type',
            style: const TextStyle(color: AppColors.textMuted),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('Cancel'),
            ),
            ElevatedButton(
              onPressed: () {
                Navigator.pop(ctx);
                permService.openSettings();
              },
              child: const Text('Open Settings'),
            ),
          ],
        );
      },
    );
  }

  void _reconnect() {
    final ws = context.read<WebSocketService>();
    final host = _serverHostController.text.trim().isEmpty
        ? '127.0.0.1'
        : _serverHostController.text.trim();
    final portText = _serverPortController.text.trim();
    final port = portText.isEmpty ? null : int.tryParse(portText);

    ws.connect(host: host, port: port);
    final portLabel = port == null ? 'auto' : port.toString();
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(SnackBar(content: Text('Reconnecting to $host:$portLabel')));
  }
}
