import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/websocket_service.dart';
import '../theme/app_theme.dart';

class BackendLogPanel extends StatefulWidget {
  const BackendLogPanel({super.key});

  @override
  State<BackendLogPanel> createState() => _BackendLogPanelState();
}

class _BackendLogPanelState extends State<BackendLogPanel> {
  final ScrollController _scrollController = ScrollController();
  bool _autoScroll = true;

  @override
  void dispose() {
    _scrollController.dispose();
    super.dispose();
  }

  void _scrollToBottom() {
    if (_autoScroll && _scrollController.hasClients) {
      _scrollController.animateTo(
        _scrollController.position.maxScrollExtent,
        duration: const Duration(milliseconds: 200),
        curve: Curves.easeOut,
      );
    }
  }

  Color _getLevelColor(String level) {
    switch (level.toUpperCase()) {
      case 'ERROR':
      case 'CRITICAL':
        return Colors.redAccent;
      case 'WARNING':
        return Colors.orangeAccent;
      case 'INFO':
        return Colors.blueAccent;
      case 'DEBUG':
        return Colors.grey;
      default:
        return AppColors.textSecondary;
    }
  }

  @override
  Widget build(BuildContext context) {
    return Consumer<WebSocketService>(
      builder: (context, ws, child) {
        final logs = ws.backendLogs;

        WidgetsBinding.instance.addPostFrameCallback((_) => _scrollToBottom());

        return Column(
          children: [
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  const Text(
                    'BACKEND TERMINAL',
                    style: TextStyle(
                      color: AppColors.textMuted,
                      fontSize: 10,
                      fontWeight: FontWeight.bold,
                      letterSpacing: 1.2,
                    ),
                  ),
                  Row(
                    children: [
                      Text(
                        'Auto-scroll',
                        style: TextStyle(
                          color: AppColors.textMuted,
                          fontSize: 10,
                        ),
                      ),
                      Transform.scale(
                        scale: 0.6,
                        child: Switch(
                          value: _autoScroll,
                          onChanged: (val) => setState(() => _autoScroll = val),
                          activeThumbColor: AppColors.accent,
                          activeTrackColor: AppColors.accent.withValues(
                            alpha: 0.35,
                          ),
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            ),
            const Divider(height: 1, color: Colors.white10),
            Expanded(
              child: Container(
                color: Colors.black.withValues(alpha: 0.3),
                child: SelectionArea(
                  child: ListView.builder(
                    controller: _scrollController,
                    padding: const EdgeInsets.symmetric(
                      horizontal: 8,
                      vertical: 8,
                    ),
                    itemCount: logs.length,
                    itemBuilder: (context, index) {
                      final log = logs[index];
                      final timestamp =
                          log['timestamp']
                              ?.toString()
                              .split('T')
                              .last
                              .split('.')
                              .first ??
                          '';
                      final level = log['level']?.toString() ?? 'INFO';
                      final message = log['message'] ?? '';
                      final loggerName =
                          log['logger']?.toString().split('.').last ?? '';

                      return Padding(
                        padding: const EdgeInsets.only(bottom: 2),
                        child: RichText(
                          text: TextSpan(
                            style: const TextStyle(
                              fontFamily: 'monospace',
                              fontSize: 11,
                              height: 1.2,
                            ),
                            children: [
                              TextSpan(
                                text: '$timestamp ',
                                style: TextStyle(
                                  color: AppColors.textMuted.withValues(
                                    alpha: 0.5,
                                  ),
                                ),
                              ),
                              TextSpan(
                                text: '${level.padRight(7)} ',
                                style: TextStyle(
                                  color: _getLevelColor(level),
                                  fontWeight: FontWeight.bold,
                                ),
                              ),
                              TextSpan(
                                text: '[$loggerName] ',
                                style: const TextStyle(
                                  color: AppColors.accentSoft,
                                  fontSize: 10,
                                ),
                              ),
                              TextSpan(
                                text: message,
                                style: const TextStyle(
                                  color: AppColors.textSecondary,
                                ),
                              ),
                            ],
                          ),
                        ),
                      );
                    },
                  ),
                ),
              ),
            ),
          ],
        );
      },
    );
  }
}
