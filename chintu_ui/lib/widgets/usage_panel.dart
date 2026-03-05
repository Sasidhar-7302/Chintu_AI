import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../theme/app_theme.dart';
import '../services/websocket_service.dart';

class UsagePanel extends StatelessWidget {
  const UsagePanel({super.key});

  @override
  Widget build(BuildContext context) {
    return Consumer<WebSocketService>(
      builder: (context, ws, child) {
        final usage = ws.usage;
        final providers = (usage['providers'] as Map?)?.cast<String, dynamic>() ?? {};
        final hints = (usage['provider_hints'] as Map?)?.cast<String, dynamic>() ?? {};
        final credits = (usage['credits'] as Map?)?.cast<String, dynamic>() ?? {};
        final cache = (usage['cache'] as Map?)?.cast<String, dynamic>() ?? {};
        final resetSeconds = usage['daily_reset_in_seconds']?.toString() ?? '';

        return ListView(
          padding: const EdgeInsets.all(12),
          children: [
            _sectionHeader('Usage Summary'),
            const SizedBox(height: 8),
            _statRow('Cache entries', cache['entries']?.toString() ?? '0'),
            _statRow('Cache hits', cache['total_hits']?.toString() ?? '0'),
            if (resetSeconds.isNotEmpty) _statRow('Daily reset in', '${resetSeconds}s'),
            const SizedBox(height: 16),
            _sectionHeader('Providers'),
            const SizedBox(height: 8),
            if (providers.isEmpty)
              _emptyState('No usage data yet')
            else
              ...providers.entries.map((entry) {
                final name = entry.key;
                final data = (entry.value as Map).cast<String, dynamic>();
                final hint = (hints[name] as Map?)?.cast<String, dynamic>() ?? {};
                final credit = credits[name];
                return _providerCard(name, data, hint, credit);
              }),
          ],
        );
      },
    );
  }

  Widget _sectionHeader(String title) {
    return Row(
      children: [
        Text(
          title,
          style: const TextStyle(
            color: AppColors.textPrimary,
            fontWeight: FontWeight.w600,
            fontSize: 13,
          ),
        ),
      ],
    );
  }

  Widget _statRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Row(
        children: [
          Expanded(
            child: Text(
              label,
              style: const TextStyle(color: AppColors.textMuted, fontSize: 11),
            ),
          ),
          Text(
            value,
            style: const TextStyle(color: AppColors.textPrimary, fontSize: 11),
          ),
        ],
      ),
    );
  }

  Widget _providerCard(String name, Map<String, dynamic> data, Map<String, dynamic> hint, dynamic credit) {
    final available = data['available']?.toString() ?? 'unknown';
    final minuteUsage = data['minute_usage']?.toString() ?? '-';
    final dailyUsage = data['daily_usage']?.toString() ?? '-';
    final inCooldown = data['in_cooldown'] == true;
    final creditText = credit == null ? 'n/a' : credit.toString();

    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppColors.surfaceStrong.withValues(alpha: 0.3),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.border.withValues(alpha: 0.4)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text(
                name.toUpperCase(),
                style: const TextStyle(
                  color: AppColors.textPrimary,
                  fontWeight: FontWeight.w600,
                  fontSize: 12,
                ),
              ),
              const SizedBox(width: 8),
              if (inCooldown)
                const Text(
                  'cooldown',
                  style: TextStyle(color: AppColors.accentDeep, fontSize: 10),
                ),
            ],
          ),
          const SizedBox(height: 6),
          _statRow('Available', available),
          _statRow('Minute usage', minuteUsage),
          _statRow('Daily usage', dailyUsage),
          _statRow('Credits (manual)', creditText),
          if (hint.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text(
              'Provider hints',
              style: const TextStyle(color: AppColors.textMuted, fontSize: 10),
            ),
            const SizedBox(height: 4),
            ...hint.entries.map((e) => _statRow(e.key, e.value.toString())),
          ],
        ],
      ),
    );
  }

  Widget _emptyState(String text) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.surfaceStrong.withValues(alpha: 0.25),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.border.withValues(alpha: 0.4)),
      ),
      child: Text(
        text,
        style: const TextStyle(color: AppColors.textMuted, fontSize: 12),
      ),
    );
  }
}
