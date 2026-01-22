import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

class CapabilityPanel extends StatelessWidget {
  final List<Map<String, dynamic>> capabilities;
  const CapabilityPanel({super.key, required this.capabilities});

  static final List<Map<String, dynamic>> defaultCapabilities = [
    {'name': 'Wake Word', 'id': 'wake_word', 'enabled': true, 'active': false},
    {'name': 'Voice Commands', 'id': 'voice_commands', 'enabled': true, 'active': false},
    {'name': 'Hand Gestures', 'id': 'hand_gestures', 'enabled': true, 'active': false},
    {'name': 'App Control', 'id': 'app_control', 'enabled': true, 'active': false},
    {'name': 'Job Search', 'id': 'job_search', 'enabled': true, 'active': false},
    {'name': 'LLM Integration', 'id': 'llm_integration', 'enabled': true, 'active': false},
  ];

  static const Map<String, IconData> _iconMap = {
    'wake_word': Icons.record_voice_over,
    'voice_commands': Icons.mic,
    'hand_gestures': Icons.pan_tool,
    'app_control': Icons.apps,
    'job_search': Icons.work,
    'llm_integration': Icons.smart_toy,
  };

  List<Map<String, dynamic>> _mergeCapabilities(List<Map<String, dynamic>> overrides) {
    final overridesById = <String, Map<String, dynamic>>{};
    for (final cap in overrides) {
      final id = cap['id']?.toString();
      if (id == null || id.isEmpty) continue;
      overridesById[id] = cap;
    }

    final merged = <Map<String, dynamic>>[];
    for (final base in defaultCapabilities) {
      final id = base['id']?.toString() ?? '';
      final override = overridesById[id] ?? const <String, dynamic>{};
      final status = override['status']?.toString();
      final enabled = override['enabled'] is bool ? override['enabled'] as bool : (base['enabled'] as bool? ?? true);
      final active = enabled && (override['active'] is bool ? override['active'] as bool : (status == 'active'));
      merged.add({
        'id': id,
        'name': override['name'] ?? base['name'],
        'enabled': enabled,
        'active': active,
      });
    }

    return merged;
  }

  @override
  Widget build(BuildContext context) {
    final caps = _mergeCapabilities(capabilities);
    final activeCount = caps.where((cap) => cap['active'] == true).length;
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.surface.withValues(alpha: 0.85),
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: AppColors.border.withValues(alpha: 0.7)),
        boxShadow: [
          BoxShadow(
            color: AppColors.accent.withValues(alpha: 0.08),
            blurRadius: 24,
            offset: const Offset(0, 12),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            children: [
              Container(
                padding: const EdgeInsets.all(6),
                decoration: BoxDecoration(
                  color: AppColors.accent.withValues(alpha: 0.15),
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: AppColors.accent.withValues(alpha: 0.4)),
                ),
                child: const Icon(Icons.auto_awesome, color: AppColors.accent, size: 14),
              ),
              const SizedBox(width: 10),
              const Expanded(
                child: Text(
                  'Capabilities',
                  style: TextStyle(
                    color: AppColors.textPrimary,
                    fontSize: 16,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                decoration: BoxDecoration(
                  color: AppColors.surfaceStrong.withValues(alpha: 0.8),
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: AppColors.border.withValues(alpha: 0.6)),
                ),
                child: Text(
                  '$activeCount/${caps.length} active',
                  style: const TextStyle(
                    color: AppColors.textMuted,
                    fontSize: 11,
                    fontWeight: FontWeight.w600,
                    letterSpacing: 0.3,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Flexible(
            child: SingleChildScrollView(
              child: Column(
                children: caps.map((cap) {
                  final status = cap['status']?.toString();
                  final enabled = cap['enabled'] as bool? ?? true;
                  final active = (cap['active'] as bool?) ?? (status == 'active');
                  return _CapabilityItem(
                    name: cap['name']?.toString() ?? '',
                    icon: _iconMap[cap['id']] ?? Icons.extension,
                    enabled: enabled,
                    active: active,
                  );
                }).toList(),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _CapabilityItem extends StatelessWidget {
  final String name;
  final IconData icon;
  final bool enabled;
  final bool active;
  const _CapabilityItem({required this.name, required this.icon, required this.enabled, required this.active});

  @override
  Widget build(BuildContext context) {
    final rowGradient = active
        ? LinearGradient(colors: [AppColors.accent.withValues(alpha: 0.12), Colors.transparent])
        : null;
    final borderColor = active
        ? AppColors.accent.withValues(alpha: 0.5)
        : AppColors.border.withValues(alpha: enabled ? 0.5 : 0.3);
    final iconGradient = enabled
        ? LinearGradient(colors: [AppColors.accent.withValues(alpha: active ? 0.9 : 0.6), AppColors.accentSoft.withValues(alpha: active ? 0.7 : 0.4)])
        : null;
    final iconShadow = active ? [BoxShadow(color: AppColors.accent.withValues(alpha: 0.35), blurRadius: 10)] : null;

    return Container(
      margin: const EdgeInsets.symmetric(vertical: 4),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
      decoration: BoxDecoration(
        gradient: rowGradient,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: borderColor),
      ),
      child: Row(children: [
        Container(
          width: 34,
          height: 34,
          decoration: BoxDecoration(
            gradient: iconGradient,
            color: enabled ? null : AppColors.surfaceStrong.withValues(alpha: 0.5),
            borderRadius: BorderRadius.circular(10),
            boxShadow: iconShadow,
          ),
          child: Icon(icon, color: enabled ? AppColors.accent : AppColors.textMuted, size: 16),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: Text(
            name,
            style: TextStyle(
              color: enabled ? AppColors.textPrimary : AppColors.textMuted,
              fontSize: 12,
              fontWeight: enabled ? FontWeight.w500 : FontWeight.normal,
            ),
          ),
        ),
        Container(
          width: 8,
          height: 8,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            gradient: active ? const LinearGradient(colors: [AppColors.success, AppColors.accent]) : null,
            color: active ? null : AppColors.surfaceStrong,
            boxShadow: active ? [BoxShadow(color: AppColors.success.withValues(alpha: 0.6), blurRadius: 6, spreadRadius: 1)] : null,
          ),
        ),
      ]),
    );
  }
}
