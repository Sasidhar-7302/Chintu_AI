import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../theme/app_theme.dart';
import '../services/websocket_service.dart';

class JobApplicationsPanel extends StatelessWidget {
  const JobApplicationsPanel({super.key});

  @override
  Widget build(BuildContext context) {
    return Consumer<WebSocketService>(
      builder: (context, ws, child) {
        final apps = ws.jobApplications;
        if (apps.isEmpty) {
          return _emptyState('No job applications logged yet');
        }
        return ListView(
          padding: const EdgeInsets.all(12),
          children: apps.map((item) => _jobCard(item)).toList(),
        );
      },
    );
  }

  Widget _jobCard(Map<String, dynamic> item) {
    final title = item['title']?.toString() ?? 'Job';
    final status = item['status']?.toString() ?? 'unknown';
    final url = item['url']?.toString() ?? '';
    final reason = item['reason']?.toString() ?? '';
    final resume = item['resume_path']?.toString() ?? '';
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
          Text(
            '$status: $title',
            style: const TextStyle(
              color: AppColors.textPrimary,
              fontWeight: FontWeight.w600,
              fontSize: 12,
            ),
          ),
          const SizedBox(height: 6),
          if (reason.isNotEmpty)
            Text(
              'Reason: $reason',
              style: const TextStyle(color: AppColors.textMuted, fontSize: 11),
            ),
          if (url.isNotEmpty)
            Text(
              'URL: $url',
              style: const TextStyle(color: AppColors.textMuted, fontSize: 11),
            ),
          if (resume.isNotEmpty)
            Text(
              'Resume: $resume',
              style: const TextStyle(color: AppColors.textMuted, fontSize: 11),
              overflow: TextOverflow.ellipsis,
            ),
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
