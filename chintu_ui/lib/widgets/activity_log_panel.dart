import 'package:flutter/material.dart';
import '../theme/app_theme.dart';
import '../services/websocket_service.dart';
import 'package:provider/provider.dart';

class ActivityLogPanel extends StatelessWidget {
  const ActivityLogPanel({super.key});

  @override
  Widget build(BuildContext context) {
    return Consumer<WebSocketService>(
      builder: (context, ws, child) {
        final logs = ws.activityLog;

        if (logs.isEmpty) {
          return Center(
            child: Text(
              'No recent activity',
              style: TextStyle(color: AppColors.textMuted.withValues(alpha: 0.5), fontSize: 12),
            ),
          );
        }

        return ListView.builder(
          padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 8),
          itemCount: logs.length,
          itemBuilder: (context, index) {
            final entry = logs[index];
            final time = entry['time'] ?? '';
            final msg = entry['message'] ?? '';
            
            return Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    time,
                    style: TextStyle(
                      fontSize: 11, 
                      color: AppColors.textMuted.withValues(alpha: 0.7),
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      msg,
                      style: const TextStyle(color: AppColors.textSecondary, fontSize: 12),
                    ),
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
