import 'package:flutter/material.dart';
import '../theme/app_theme.dart';
import 'system_health_panel.dart';
import 'scheduled_tasks_panel.dart';
import 'activity_log_panel.dart';
import 'hud_panel.dart';
import 'sessions_panel.dart';
import 'change_log_panel.dart';
import 'usage_panel.dart';
import 'job_applications_panel.dart';

class ControlSidePanel extends StatelessWidget {
  final List<Map<String, dynamic>> capabilities;
  final Map<String, dynamic> hud;

  const ControlSidePanel({super.key, required this.capabilities, required this.hud});

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: AppColors.surfaceElevated.withValues(alpha: 0.85),
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: AppColors.border.withValues(alpha: 0.7)),
        boxShadow: [
          BoxShadow(
             color: AppColors.accentDeep.withValues(alpha: 0.12),
             blurRadius: 24,
             offset: const Offset(0, 12),
          ),
        ],
      ),
      child: DefaultTabController(
        length: 8,
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.all(12),
              child: Container(
                height: 36,
                decoration: BoxDecoration(
                  color: AppColors.surfaceStrong.withValues(alpha: 0.5),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: TabBar(
                  indicator: BoxDecoration(
                    color: AppColors.accent.withValues(alpha: 0.15),
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(color: AppColors.accent.withValues(alpha: 0.3)),
                  ),
                  labelColor: AppColors.accent,
                  unselectedLabelColor: AppColors.textMuted,
                  labelStyle: const TextStyle(fontWeight: FontWeight.w600, fontSize: 12),
                  indicatorSize: TabBarIndicatorSize.tab,
                  dividerColor: Colors.transparent,
                  tabs: const [
                    Tab(text: "Health"),
                    Tab(text: "Usage"),
                    Tab(text: "Jobs"),
                    Tab(text: "Tasks"),
                    Tab(text: "Sessions"),
                    Tab(text: "Changes"),
                    Tab(text: "Activity"),
                    Tab(text: "HUD"),
                  ],
                ),
              ),
            ),
            Expanded(
              child: TabBarView(
                children: [
                   // 1. Health (Reuse existing logic but strip container since we have one here)
                   // We'll wrap SystemHealthPanel's content. Or just use it directly, 
                   // but SystemHealthPanel has its own container. 
                   // Let's modify SystemHealthPanel to be transparent or just nest it. 
                   // Since I can't easily modify SystemHealthPanel to remove container without edit, 
                   // I'll just use it. It might look double-bordered but acceptable for now.
                   // Actually, better to wrap it in a transparent theme or just re-implement the internal list here.
                   // For speed, let's keep it simple: Use the panel but maybe with 0 padding/elevation if possible?
                   // No, it handles its own decor.
                   // Let's just put it there. The user wants functionality.
                   
                   // Better: Extract list from SystemHealthPanel? 
                   // I'll just instantiate it. It has its own decoration, so it will look like a "Card in a Card".
                   // That is okay.
                   ClipRRect(borderRadius: BorderRadius.circular(18), child: SystemHealthPanel(capabilities: capabilities)),
                   const UsagePanel(),
                   const JobApplicationsPanel(),
                   const ScheduledTasksPanel(),
                   const SessionsPanel(),
                   const ChangeLogPanel(),
                   const ActivityLogPanel(),
                   HudPanel(hud: hud),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
