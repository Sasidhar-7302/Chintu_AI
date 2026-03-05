import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

class SystemHealthPanel extends StatelessWidget {
  final List<Map<String, dynamic>> capabilities;
  
  const SystemHealthPanel({super.key, required this.capabilities});

  static const Map<String, IconData> _iconMap = {
    'wake_word': Icons.record_voice_over,
    'voice_commands': Icons.mic,
    'hand_gestures': Icons.pan_tool,
    'app_control': Icons.apps,
    'job_search': Icons.work,
    'llm_integration': Icons.smart_toy,
    'docker': Icons.layers,
    'telegram': Icons.send,
    'orchestrator': Icons.schedule,
    'memory': Icons.memory,
    'vision': Icons.visibility,
    'search': Icons.search,
  };

  @override
  Widget build(BuildContext context) {
    final issues = capabilities.where((c) {
      final status = c['status']?.toString().toLowerCase();
      final enabled = c['enabled'] == true;
      return enabled && (status == 'error' || status == 'inactive' || status == 'testing');
    }).toList();

    final active = capabilities.where((c) {
      final status = c['status']?.toString().toLowerCase();
      final enabled = c['enabled'] == true;
      return enabled && (status == 'active' || status == 'healthy');
    }).toList();

    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 8, 12, 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.monitor_heart, color: AppColors.textPrimary, size: 16),
              const SizedBox(width: 8),
              const Text('System Health', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16, color: AppColors.textPrimary)),
              const Spacer(),
              if (issues.isNotEmpty)
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                  decoration: BoxDecoration(
                    color: AppColors.accentDeep.withValues(alpha: 0.15),
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(color: AppColors.accentDeep.withValues(alpha: 0.45)),
                  ),
                  child: Text('${issues.length} Issues', style: const TextStyle(color: AppColors.accentSoft, fontSize: 10, fontWeight: FontWeight.bold)),
                ),
            ],
          ),
          const SizedBox(height: 12),
          Expanded(
            child: SingleChildScrollView(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if (issues.isNotEmpty) ...[
                    const Padding(
                      padding: EdgeInsets.only(bottom: 8),
                      child: Text('Needs Attention', style: TextStyle(color: AppColors.accentSoft, fontSize: 12, fontWeight: FontWeight.w600)),
                    ),
                    ...issues.map((c) => _HealthItem(
                      name: c['name'] ?? 'Unknown',
                      status: c['status'] ?? 'Error',
                      icon: _iconMap[c['id']] ?? Icons.extension,
                      isError: true,
                    )),
                    const SizedBox(height: 12),
                  ],
                  const Padding(
                    padding: EdgeInsets.only(bottom: 8),
                    child: Text('Active Systems', style: TextStyle(color: AppColors.textMuted, fontSize: 12, fontWeight: FontWeight.w600)),
                  ),
                  if (active.isEmpty)
                     const Padding(
                       padding: EdgeInsets.all(8.0),
                       child: Text('Connecting to backend...', style: TextStyle(color: AppColors.textMuted, fontSize: 12, fontStyle: FontStyle.italic)),
                     ),
                  ...active.map((c) => _HealthItem(
                    name: c['name'] ?? 'Unknown',
                    status: c['status'] ?? 'Active',
                    icon: _iconMap[c['id']] ?? Icons.check_circle,
                    isError: false,
                  )),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _HealthItem extends StatelessWidget {
  final String name;
  final String status;
  final IconData icon;
  final bool isError;

  const _HealthItem({required this.name, required this.status, required this.icon, required this.isError});

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 6),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        color: AppColors.surfaceStrong.withValues(alpha: isError ? 0.28 : 0.22),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.border.withValues(alpha: 0.4)),
      ),
      child: Row(
        children: [
          Icon(icon, size: 14, color: isError ? AppColors.accentSoft : AppColors.accent),
          const SizedBox(width: 10),
          Expanded(
            child: Text(name, style: const TextStyle(color: AppColors.textPrimary, fontSize: 12, fontWeight: FontWeight.w500)),
          ),
          Text(status.toUpperCase(), style: const TextStyle(color: AppColors.accentSoft, fontSize: 10, fontWeight: FontWeight.bold)),
        ],
      ),
    );
  }
}
