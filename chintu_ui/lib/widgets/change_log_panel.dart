import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../theme/app_theme.dart';
import '../services/websocket_service.dart';

class ChangeLogPanel extends StatelessWidget {
  const ChangeLogPanel({super.key});

  @override
  Widget build(BuildContext context) {
    return Consumer<WebSocketService>(
      builder: (context, ws, child) {
        final changes = ws.changeLog;
        if (changes.isEmpty) {
          return Center(
            child: Text(
              'No recorded changes yet.',
              style: TextStyle(color: AppColors.textMuted.withValues(alpha: 0.8), fontSize: 12),
            ),
          );
        }
        return ListView.builder(
          padding: const EdgeInsets.all(12),
          itemCount: changes.length,
          itemBuilder: (context, index) {
            final change = changes[index];
            final id = change['id'] ?? '';
            final filePath = change['file_path'] ?? '';
            final issue = change['issue'] ?? '';
            final created = change['created_at'] ?? '';
            final commit = change['commit_sha'] ?? '';

            return Container(
              margin: const EdgeInsets.only(bottom: 8),
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
                    filePath.toString(),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      color: AppColors.textPrimary,
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    'ID: $id • $created',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(color: AppColors.textSecondary, fontSize: 11),
                  ),
                  if (issue.toString().isNotEmpty) ...[
                    const SizedBox(height: 4),
                    Text(
                      issue.toString(),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(color: AppColors.textMuted, fontSize: 11),
                    ),
                  ],
                  if (commit.toString().isNotEmpty) ...[
                    const SizedBox(height: 4),
                    Text(
                      'Commit: $commit',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(color: AppColors.textSecondary, fontSize: 11),
                    ),
                  ],
                  const SizedBox(height: 8),
                  Row(
                    children: [
                      OutlinedButton(
                        onPressed: id.toString().isEmpty
                            ? null
                            : () => ws.sendCommand('commit change $id'),
                        child: const Text('Commit'),
                      ),
                      const SizedBox(width: 8),
                      OutlinedButton(
                        onPressed: id.toString().isEmpty
                            ? null
                            : () => ws.sendCommand('rollback change $id'),
                        child: const Text('Rollback'),
                      ),
                    ],
                  ),
                ],
              ),
            );
          },
        );
      },
    );
  }
}
