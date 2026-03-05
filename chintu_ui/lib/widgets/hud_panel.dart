import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

class HudPanel extends StatelessWidget {
  final Map<String, dynamic> hud;
  final bool embedded;

  const HudPanel({super.key, required this.hud, this.embedded = false});

  @override
  Widget build(BuildContext context) {
    final intent = hud['intent']?.toString() ?? '';
    final activeTools = List<String>.from(hud['active_tools'] as List? ?? const []);
    final memoryContext = hud['memory_context']?.toString() ?? '';
    final pending = hud['pending'] as Map<String, dynamic>? ?? {};
    final pendingCount = pending['pending_count'] ?? 0;

    Widget content = Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (!embedded) ...[
          Row(
            children: [
              Icon(Icons.hub, color: AppColors.accent, size: 18),
              const SizedBox(width: 8),
              Text(
                'Neural HUD',
                style: Theme.of(context).textTheme.titleSmall?.copyWith(
                      color: AppColors.textPrimary,
                      fontWeight: FontWeight.w600,
                    ),
              ),
              const Spacer(),
              _buildPendingChip(context, pendingCount),
            ],
          ),
          const SizedBox(height: 12),
        ] else if (pendingCount > 0) ...[
             // Show pending count even if embedded, maybe?
             // Actually _buildSectionCard usually has trailing widget support.
             // We'll skip for now to save space, or put it in content.
        ],
        _buildRow('Intent', intent.isEmpty ? '—' : intent),
        const SizedBox(height: 10),
        _buildChips(activeTools),
        const SizedBox(height: 14),
        Text(
          'Memory context',
          style: Theme.of(context).textTheme.labelMedium?.copyWith(
                color: AppColors.textMuted,
                fontWeight: FontWeight.w600,
              ),
        ),
        const SizedBox(height: 8),
        embedded 
          ? Text(
              memoryContext.isEmpty ? 'No memory context loaded.' : memoryContext,
              maxLines: 4,
              overflow: TextOverflow.ellipsis,
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: AppColors.textSecondary,
                    height: 1.35,
                  ),
            )
          : Expanded(
              child: SingleChildScrollView(
                child: Text(
                  memoryContext.isEmpty ? 'No memory context loaded.' : memoryContext,
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: AppColors.textSecondary,
                        height: 1.35,
                      ),
                ),
              ),
            ),
      ],
    );

    if (embedded) {
      return content;
    }

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.surface.withValues(alpha: 0.85),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppColors.border.withValues(alpha: 0.5)),
        boxShadow: [
          BoxShadow(
            color: AppColors.accent.withValues(alpha: 0.08),
            blurRadius: 24,
            offset: const Offset(0, 10),
          ),
        ],
      ),
      child: content,
    );
  }

  Widget _buildPendingChip(BuildContext context, int count) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: AppColors.surfaceStrong.withValues(alpha: 0.6),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.border.withValues(alpha: 0.4)),
      ),
      child: Text(
        'Pending: $count',
        style: Theme.of(context).textTheme.labelSmall?.copyWith(
              color: AppColors.textMuted,
              fontWeight: FontWeight.w600,
            ),
      ),
    );
  }

  Widget _buildRow(String label, String value) {
    return Row(
      children: [
        Text(
          '$label:',
          style: const TextStyle(
            color: AppColors.textMuted,
            fontWeight: FontWeight.w600,
            fontSize: 12,
          ),
        ),
        const SizedBox(width: 8),
        Expanded(
          child: Text(
            value,
            style: const TextStyle(
              color: AppColors.textPrimary,
              fontWeight: FontWeight.w600,
              fontSize: 13,
            ),
            overflow: TextOverflow.ellipsis,
          ),
        ),
      ],
    );
  }

  Widget _buildChips(List<String> activeTools) {
    if (activeTools.isEmpty) {
      return Row(
        children: const [
          Icon(Icons.handyman_outlined, color: AppColors.textMuted, size: 14),
          SizedBox(width: 6),
          Text(
            'No active tools',
            style: TextStyle(color: AppColors.textMuted, fontSize: 12),
          ),
        ],
      );
    }
    return Wrap(
      spacing: 6,
      runSpacing: 6,
      children: activeTools.map((tool) {
        return Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
          decoration: BoxDecoration(
            color: AppColors.accent.withValues(alpha: 0.15),
            borderRadius: BorderRadius.circular(14),
            border: Border.all(color: AppColors.accent.withValues(alpha: 0.4)),
          ),
          child: Text(
            tool,
            style: const TextStyle(
              color: AppColors.textPrimary,
              fontSize: 11,
              fontWeight: FontWeight.w600,
            ),
          ),
        );
      }).toList(),
    );
  }
}
