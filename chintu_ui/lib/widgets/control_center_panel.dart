import 'dart:io';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:flutter/services.dart';

import '../services/websocket_service.dart';
import '../theme/app_theme.dart';
import 'glass_card.dart';

class ControlCenterPanel extends StatelessWidget {
  final VoidCallback? onClose;

  const ControlCenterPanel({super.key, this.onClose});

  Color _projectStatusColor(String status) {
    switch (status) {
      case 'active':
        return AppColors.accent;
      case 'paused':
        return AppColors.warning;
      case 'completed':
        return AppColors.success;
      case 'failed':
        return AppColors.danger;
      case 'cancelled':
        return AppColors.textMuted;
      default:
        return AppColors.textMuted;
    }
  }

  Color _stepStatusColor(String status) {
    switch (status) {
      case 'running':
        return AppColors.accentSoft;
      case 'runnable':
        return AppColors.accent;
      case 'waiting_approval':
        return AppColors.warning;
      case 'waiting_input':
        return AppColors.warning;
      case 'failed':
        return AppColors.danger;
      case 'completed':
        return AppColors.success;
      default:
        return AppColors.textMuted;
    }
  }

  Color _runStatusColor(String status) {
    switch (status) {
      case 'running':
        return AppColors.accent;
      case 'queued':
        return AppColors.accentSoft;
      case 'waiting_approval':
        return AppColors.warning;
      case 'waiting_input':
        return AppColors.warning;
      case 'completed':
        return AppColors.success;
      case 'failed':
        return AppColors.danger;
      case 'cancelled':
        return AppColors.textMuted;
      case 'timed_out':
        return AppColors.danger;
      default:
        return AppColors.textMuted;
    }
  }

  String _projectName(WebSocketService ws, String projectId) {
    final match = ws.orchestratorProjects.firstWhere(
      (p) => p['id']?.toString() == projectId,
      orElse: () => const <String, dynamic>{},
    );
    return match['name']?.toString() ?? projectId;
  }

  String _stepTitle(WebSocketService ws, String projectId, String stepId) {
    final steps =
        ws.orchestratorStepsByProject[projectId] ??
        const <Map<String, dynamic>>[];
    final step = steps.firstWhere(
      (s) => s['id']?.toString() == stepId,
      orElse: () => const <String, dynamic>{},
    );
    return step['title']?.toString() ?? stepId;
  }

  Future<void> _promptSetInput(
    BuildContext context,
    WebSocketService ws, {
    required String projectId,
    required String keyName,
  }) async {
    final controller = TextEditingController();
    bool isSecret = RegExp(
      r'(key|token|secret|password)',
      caseSensitive: false,
    ).hasMatch(keyName);

    final result = await showDialog<bool>(
      context: context,
      builder: (context) {
        return StatefulBuilder(
          builder: (context, setState) {
            return AlertDialog(
              title: const Text('Set Input'),
              content: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    _projectName(ws, projectId),
                    style: const TextStyle(
                      color: AppColors.textMuted,
                      fontSize: 12,
                    ),
                  ),
                  const SizedBox(height: 10),
                  Text(
                    keyName,
                    style: const TextStyle(fontWeight: FontWeight.w600),
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: controller,
                    obscureText: isSecret,
                    decoration: InputDecoration(
                      hintText: isSecret ? 'Enter secret value' : 'Enter value',
                    ),
                    autofocus: true,
                    onSubmitted: (_) => Navigator.of(context).pop(true),
                  ),
                  const SizedBox(height: 10),
                  Row(
                    children: [
                      Switch(
                        value: isSecret,
                        onChanged: (v) => setState(() => isSecret = v),
                      ),
                      const SizedBox(width: 8),
                      const Text('Secret'),
                    ],
                  ),
                ],
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.of(context).pop(false),
                  child: const Text('Cancel'),
                ),
                FilledButton(
                  onPressed: () => Navigator.of(context).pop(true),
                  child: const Text('Save'),
                ),
              ],
            );
          },
        );
      },
    );

    if (result == true) {
      ws.setOrchestratorInput(
        projectId: projectId,
        key: keyName,
        value: controller.text,
        isSecret: isSecret,
      );
    }
  }

  Widget _sectionHeader(String title, {Widget? trailing}) {
    return Row(
      children: [
        Text(
          title,
          style: const TextStyle(
            color: AppColors.textPrimary,
            fontSize: 13,
            fontWeight: FontWeight.w700,
          ),
        ),
        const Spacer(),
        if (trailing != null) trailing,
      ],
    );
  }

  Widget _kv(String k, String v, {Color? vColor}) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Text(
              k,
              style: const TextStyle(color: AppColors.textMuted, fontSize: 11),
            ),
          ),
          const SizedBox(width: 10),
          Flexible(
            child: Text(
              v,
              style: TextStyle(
                color: vColor ?? AppColors.textPrimary,
                fontSize: 11,
                fontWeight: FontWeight.w600,
              ),
              overflow: TextOverflow.ellipsis,
              maxLines: 2,
              textAlign: TextAlign.right,
            ),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Consumer<WebSocketService>(
      builder: (context, ws, child) {
        final connected = ws.isConnected;
        final state = ws.assistantState;

        final orchProjects = ws.orchestratorProjects;
        final orchApprovals = ws.orchestratorApprovals
            .where((a) => (a['status']?.toString() ?? '') != 'rejected')
            .toList();
        final pendingCodeApprovals = ws.pendingCodeApprovals;

        final hudPending = ws.hud['pending'];
        final bool hasPendingCapability =
            (hudPending is Map) && (hudPending['capability_pending'] == true);
        final String pendingCapabilityName = (hudPending is Map)
            ? (hudPending['capability_pending_capability']?.toString() ?? '')
            : '';
        final String pendingCapabilityMessage = (hudPending is Map)
            ? (hudPending['capability_pending_message']?.toString() ?? '')
            : '';

        final tasks = List<Map<String, dynamic>>.from(ws.scheduledTasks);
        tasks.sort((a, b) {
          DateTime? parse(dynamic v) {
            if (v == null) return null;
            try {
              return DateTime.parse(v.toString());
            } catch (_) {
              return null;
            }
          }

          final an = parse(a['next_run']);
          final bn = parse(b['next_run']);
          if (an == null && bn == null) return 0;
          if (an == null) return 1;
          if (bn == null) return -1;
          return an.compareTo(bn);
        });

        final runSnap = ws.runsSnapshot;
        final runTimeline = ws.runTimeline;
        final runs = <Map<String, dynamic>>[];
        final rawRuns = runSnap['runs'];
        if (rawRuns is List) {
          for (final r in rawRuns) {
            if (r is Map) runs.add(Map<String, dynamic>.from(r));
          }
        }
        Map<String, dynamic>? activeRun;
        for (final r in runs) {
          final st = r['status']?.toString() ?? '';
          if (st == 'running' ||
              st == 'waiting_approval' ||
              st == 'waiting_input') {
            activeRun = r;
            break;
          }
        }
        activeRun ??= runs.isNotEmpty ? runs.first : null;
        final run = activeRun;

        return GlassCard(
          borderRadius: BorderRadius.circular(20),
          padding: const EdgeInsets.all(14),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  const Icon(
                    Icons.dashboard_outlined,
                    color: AppColors.accent,
                    size: 18,
                  ),
                  const SizedBox(width: 8),
                  const Text(
                    'Control Center',
                    style: TextStyle(
                      color: AppColors.textPrimary,
                      fontSize: 16,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  const Spacer(),
                  IconButton(
                    onPressed: ws.requestOrchestratorSnapshot,
                    tooltip: 'Refresh',
                    icon: const Icon(
                      Icons.refresh,
                      size: 18,
                      color: AppColors.textMuted,
                    ),
                  ),
                  if (onClose != null)
                    IconButton(
                      onPressed: onClose,
                      tooltip: 'Close',
                      icon: const Icon(
                        Icons.close,
                        size: 18,
                        color: AppColors.textMuted,
                      ),
                    ),
                ],
              ),
              const SizedBox(height: 10),
              Expanded(
                child: ListView(
                  padding: EdgeInsets.zero,
                  children: [
                    _sectionHeader('Now'),
                    const SizedBox(height: 10),
                    _kv(
                      'Connection',
                      connected ? 'Active' : 'Disconnected',
                      vColor: connected ? AppColors.accent : AppColors.danger,
                    ),
                    _kv('Assistant', state.isNotEmpty ? state : 'unknown'),
                    _kv(
                      'Capability',
                      ws.lastCapability.isNotEmpty ? ws.lastCapability : '-',
                    ),
                    _kv('Model', ws.lastModel.isNotEmpty ? ws.lastModel : '-'),
                    _kv('Trace', ws.traceId.isNotEmpty ? ws.traceId : '-'),
                    if (ws.speakingText.trim().isNotEmpty) ...[
                      const SizedBox(height: 8),
                      Container(
                        padding: const EdgeInsets.all(10),
                        decoration: BoxDecoration(
                          color: AppColors.surfaceStrong.withValues(
                            alpha: 0.35,
                          ),
                          borderRadius: BorderRadius.circular(12),
                          border: Border.all(
                            color: AppColors.border.withValues(alpha: 0.4),
                          ),
                        ),
                        child: Text(
                          ws.speakingText,
                          style: const TextStyle(
                            color: AppColors.textSecondary,
                            fontSize: 11,
                            height: 1.35,
                          ),
                          maxLines: 4,
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                    ],
                    const SizedBox(height: 14),
                    Container(
                      height: 1,
                      color: AppColors.border.withValues(alpha: 0.5),
                    ),
                    const SizedBox(height: 14),

                    _sectionHeader(
                      'Runs',
                      trailing: Text(
                        '${runs.length}',
                        style: const TextStyle(
                          color: AppColors.textMuted,
                          fontSize: 12,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ),
                    const SizedBox(height: 10),
                    if (run == null)
                      const Text(
                        'No runs yet',
                        style: TextStyle(
                          color: AppColors.textMuted,
                          fontSize: 12,
                        ),
                      )
                    else ...[
                      _RunSummaryCard(
                        title:
                            run['user_text']?.toString() ??
                            run['id']?.toString() ??
                            'Run',
                        subtitle:
                            'Status: ${run['status']?.toString() ?? 'unknown'}',
                        color: _runStatusColor(
                          run['status']?.toString() ?? '',
                        ),
                        runId: run['id']?.toString() ?? '',
                        pendingApprovalRunId:
                            runSnap['pending_confirmation_run_id']
                                ?.toString() ??
                            '',
                        onCancel: () {
                          final rid = run['id']?.toString() ?? '';
                          if (rid.trim().isNotEmpty) {
                            ws.cancelRun(rid);
                          } else {
                            ws.sendCommand('stop');
                          }
                        },
                        onRefresh: () => ws.requestOrchestratorSnapshot(),
                      ),
                      if ((run['result_summary']?.toString() ?? '')
                          .trim()
                          .isNotEmpty) ...[
                        const SizedBox(height: 8),
                        Container(
                          padding: const EdgeInsets.all(10),
                          decoration: BoxDecoration(
                            color: AppColors.surfaceStrong.withValues(
                              alpha: 0.24,
                            ),
                            borderRadius: BorderRadius.circular(12),
                            border: Border.all(
                              color: AppColors.border.withValues(alpha: 0.4),
                            ),
                          ),
                          child: Text(
                            run['result_summary']?.toString() ?? '',
                            style: const TextStyle(
                              color: AppColors.textSecondary,
                              fontSize: 11,
                              height: 1.35,
                            ),
                            maxLines: 4,
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                      ],
                      if ((run['receipt_path']?.toString() ?? '')
                          .trim()
                          .isNotEmpty) ...[
                        const SizedBox(height: 8),
                        _EvidenceRow(
                          kind: 'receipt',
                          summary: 'Run receipt',
                          value: run['receipt_path']?.toString() ?? '',
                        ),
                      ],
                      const SizedBox(height: 10),
                      if (runTimeline.isEmpty)
                        const Text(
                          'No run events yet',
                          style: TextStyle(
                            color: AppColors.textMuted,
                            fontSize: 11,
                          ),
                        )
                      else
                        for (final e in runTimeline.reversed.take(6))
                          _RunEventRow(event: e),
                    ],
                    const SizedBox(height: 14),
                    Container(
                      height: 1,
                      color: AppColors.border.withValues(alpha: 0.5),
                    ),
                    const SizedBox(height: 14),

                    _sectionHeader(
                      'Approvals',
                      trailing: Text(
                        '${orchApprovals.length + pendingCodeApprovals.length + (hasPendingCapability ? 1 : 0)}',
                        style: const TextStyle(
                          color: AppColors.textMuted,
                          fontSize: 12,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ),
                    const SizedBox(height: 10),
                    if (orchApprovals.isEmpty &&
                        pendingCodeApprovals.isEmpty &&
                        !hasPendingCapability)
                      const Text(
                        'No pending approvals',
                        style: TextStyle(
                          color: AppColors.textMuted,
                          fontSize: 12,
                        ),
                      )
                    else ...[
                      if (hasPendingCapability)
                        _ApprovalCard(
                          title: 'Confirm action',
                          subtitle: pendingCapabilityName.isNotEmpty
                              ? pendingCapabilityName
                              : 'Pending action',
                          body: pendingCapabilityMessage.isNotEmpty
                              ? pendingCapabilityMessage
                              : 'Chintu is waiting for your confirmation.',
                          color: AppColors.warning,
                          onApprove: () => ws.sendCommand('confirm'),
                          onReject: () => ws.sendCommand('cancel'),
                        ),
                      for (final a in orchApprovals.take(5))
                        _ApprovalCard(
                          title: _projectName(
                            ws,
                            a['project_id']?.toString() ?? '',
                          ),
                          subtitle: _stepTitle(
                            ws,
                            a['project_id']?.toString() ?? '',
                            a['step_id']?.toString() ?? '',
                          ),
                          body: a['reason']?.toString() ?? '',
                          color: AppColors.warning,
                          onApprove: () => ws.approveOrchestratorStep(
                            a['step_id']?.toString() ?? '',
                            true,
                          ),
                          onReject: () => ws.approveOrchestratorStep(
                            a['step_id']?.toString() ?? '',
                            false,
                          ),
                        ),
                      for (final r in pendingCodeApprovals.take(3))
                        _ApprovalCard(
                          title: 'Code change',
                          subtitle: r['file']?.toString() ?? 'Unknown file',
                          body: (r['reason']?.toString() ?? '').isNotEmpty
                              ? (r['reason']?.toString() ?? '')
                              : 'Approve file edit?',
                          color: AppColors.accent,
                          onApprove: () => ws.sendCodeApprovalResponse(
                            r['request_id']?.toString() ?? '',
                            true,
                          ),
                          onReject: () => ws.sendCodeApprovalResponse(
                            r['request_id']?.toString() ?? '',
                            false,
                          ),
                        ),
                      if (orchApprovals.length > 5 ||
                          pendingCodeApprovals.length > 3)
                        const Padding(
                          padding: EdgeInsets.only(top: 6),
                          child: Text(
                            'More pending approvals exist. Use Refresh or open the A2UI overlay.',
                            style: TextStyle(
                              color: AppColors.textMuted,
                              fontSize: 11,
                            ),
                          ),
                        ),
                    ],

                    const SizedBox(height: 14),
                    Container(
                      height: 1,
                      color: AppColors.border.withValues(alpha: 0.5),
                    ),
                    const SizedBox(height: 14),

                    _sectionHeader('Inputs Needed'),
                    const SizedBox(height: 10),
                    if (orchProjects.every(
                      (p) => ws
                          .missingInputsForProject(p['id']?.toString() ?? '')
                          .isEmpty,
                    ))
                      const Text(
                        'No missing inputs',
                        style: TextStyle(
                          color: AppColors.textMuted,
                          fontSize: 12,
                        ),
                      )
                    else
                      for (final p in orchProjects)
                        ...ws
                            .missingInputsForProject(p['id']?.toString() ?? '')
                            .take(6)
                            .map(
                              (key) => _MissingInputRow(
                                projectName:
                                    p['name']?.toString() ??
                                    p['id']?.toString() ??
                                    '',
                                keyName: key,
                                onSet: () => _promptSetInput(
                                  context,
                                  ws,
                                  projectId: p['id']?.toString() ?? '',
                                  keyName: key,
                                ),
                              ),
                            ),

                    const SizedBox(height: 14),
                    Container(
                      height: 1,
                      color: AppColors.border.withValues(alpha: 0.5),
                    ),
                    const SizedBox(height: 14),

                    _sectionHeader('Projects'),
                    const SizedBox(height: 10),
                    if (orchProjects.isEmpty)
                      const Text(
                        'No orchestrator projects yet',
                        style: TextStyle(
                          color: AppColors.textMuted,
                          fontSize: 12,
                        ),
                      )
                    else
                      for (final p in orchProjects.take(8))
                        _ProjectTile(
                          project: p,
                          steps:
                              ws.orchestratorStepsByProject[p['id']
                                      ?.toString() ??
                                  ''] ??
                              const <Map<String, dynamic>>[],
                          missingInputsCount: ws
                              .missingInputsForProject(
                                p['id']?.toString() ?? '',
                              )
                              .length,
                          statusColor: _projectStatusColor(
                            p['status']?.toString() ?? '',
                          ),
                          stepStatusColor: _stepStatusColor,
                          onPause: () => ws.pauseOrchestratorProject(
                            p['id']?.toString() ?? '',
                          ),
                          onResume: () => ws.resumeOrchestratorProject(
                            p['id']?.toString() ?? '',
                          ),
                          onCancel: () => ws.cancelOrchestratorProject(
                            p['id']?.toString() ?? '',
                          ),
                        ),

                    const SizedBox(height: 14),
                    Container(
                      height: 1,
                      color: AppColors.border.withValues(alpha: 0.5),
                    ),
                    const SizedBox(height: 14),

                    _sectionHeader('Scheduled'),
                    const SizedBox(height: 10),
                    if (tasks.isEmpty)
                      const Text(
                        'No scheduled tasks',
                        style: TextStyle(
                          color: AppColors.textMuted,
                          fontSize: 12,
                        ),
                      )
                    else
                      for (final t in tasks.take(4))
                        _ScheduledTaskRow(
                          name: t['name']?.toString() ?? 'Unnamed task',
                          nextRun: t['next_run']?.toString() ?? '',
                          onCancel: () => ws.sendCommand(
                            'cancel scheduled task ${t['id']}',
                          ),
                        ),
                  ],
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}

class _ApprovalCard extends StatelessWidget {
  final String title;
  final String subtitle;
  final String body;
  final Color color;
  final VoidCallback onApprove;
  final VoidCallback onReject;

  const _ApprovalCard({
    required this.title,
    required this.subtitle,
    required this.body,
    required this.color,
    required this.onApprove,
    required this.onReject,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppColors.surfaceStrong.withValues(alpha: 0.32),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: color.withValues(alpha: 0.35)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 8,
                height: 8,
                decoration: BoxDecoration(color: color, shape: BoxShape.circle),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  title,
                  style: const TextStyle(
                    color: AppColors.textPrimary,
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                  ),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            subtitle,
            style: const TextStyle(
              color: AppColors.textMuted,
              fontSize: 11,
              fontWeight: FontWeight.w600,
            ),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
          ),
          if (body.trim().isNotEmpty) ...[
            const SizedBox(height: 8),
            Text(
              body,
              style: const TextStyle(
                color: AppColors.textSecondary,
                fontSize: 11,
                height: 1.25,
              ),
              maxLines: 3,
              overflow: TextOverflow.ellipsis,
            ),
          ],
          const SizedBox(height: 10),
          Row(
            children: [
              Expanded(
                child: OutlinedButton(
                  onPressed: onReject,
                  style: OutlinedButton.styleFrom(
                    foregroundColor: AppColors.textPrimary,
                    side: BorderSide(
                      color: AppColors.border.withValues(alpha: 0.8),
                    ),
                    padding: const EdgeInsets.symmetric(vertical: 10),
                  ),
                  child: const Text(
                    'Reject',
                    style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700),
                  ),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: FilledButton(
                  onPressed: onApprove,
                  style: FilledButton.styleFrom(
                    backgroundColor: color,
                    foregroundColor: Colors.black,
                    padding: const EdgeInsets.symmetric(vertical: 10),
                  ),
                  child: const Text(
                    'Approve',
                    style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800),
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _RunSummaryCard extends StatelessWidget {
  final String title;
  final String subtitle;
  final Color color;
  final String runId;
  final String pendingApprovalRunId;
  final VoidCallback onCancel;
  final VoidCallback onRefresh;

  const _RunSummaryCard({
    required this.title,
    required this.subtitle,
    required this.color,
    required this.runId,
    required this.pendingApprovalRunId,
    required this.onCancel,
    required this.onRefresh,
  });

  @override
  Widget build(BuildContext context) {
    final shortId = runId.isNotEmpty
        ? runId.substring(0, runId.length >= 8 ? 8 : runId.length)
        : '';
    final needsApproval =
        pendingApprovalRunId.isNotEmpty && pendingApprovalRunId == runId;

    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppColors.surfaceStrong.withValues(alpha: 0.32),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: color.withValues(alpha: 0.35)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 8,
                height: 8,
                decoration: BoxDecoration(color: color, shape: BoxShape.circle),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  title,
                  style: const TextStyle(
                    color: AppColors.textPrimary,
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                  ),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              if (shortId.isNotEmpty)
                Text(
                  shortId,
                  style: const TextStyle(
                    color: AppColors.textMuted,
                    fontSize: 11,
                    fontWeight: FontWeight.w700,
                  ),
                ),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            subtitle,
            style: const TextStyle(
              color: AppColors.textMuted,
              fontSize: 11,
              fontWeight: FontWeight.w600,
            ),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
          ),
          if (needsApproval) ...[
            const SizedBox(height: 8),
            const Text(
              'Waiting for approval',
              style: TextStyle(
                color: AppColors.warning,
                fontSize: 11,
                fontWeight: FontWeight.w700,
              ),
            ),
          ],
          const SizedBox(height: 10),
          Row(
            children: [
              Expanded(
                child: OutlinedButton(
                  onPressed: onCancel,
                  style: OutlinedButton.styleFrom(
                    foregroundColor: AppColors.textPrimary,
                    side: BorderSide(
                      color: AppColors.border.withValues(alpha: 0.8),
                    ),
                    padding: const EdgeInsets.symmetric(vertical: 10),
                  ),
                  child: const Text(
                    'Stop',
                    style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700),
                  ),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: FilledButton(
                  onPressed: onRefresh,
                  style: FilledButton.styleFrom(
                    backgroundColor: AppColors.accent,
                    foregroundColor: Colors.black,
                    padding: const EdgeInsets.symmetric(vertical: 10),
                  ),
                  child: const Text(
                    'Refresh',
                    style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800),
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _RunEventRow extends StatelessWidget {
  final Map<String, dynamic> event;

  const _RunEventRow({required this.event});

  Color _statusColor(String status) {
    switch (status) {
      case 'running':
        return AppColors.accentSoft;
      case 'completed':
        return AppColors.success;
      case 'failed':
        return AppColors.danger;
      case 'waiting_approval':
      case 'waiting_input':
        return AppColors.warning;
      default:
        return AppColors.textMuted;
    }
  }

  @override
  Widget build(BuildContext context) {
    final action = event['action']?.toString() ?? '';
    final run = event['run'] is Map
        ? Map<String, dynamic>.from(event['run'] as Map)
        : const <String, dynamic>{};
    final step = event['step'] is Map
        ? Map<String, dynamic>.from(event['step'] as Map)
        : const <String, dynamic>{};

    final title = (step['title']?.toString() ?? '').isNotEmpty
        ? step['title']?.toString() ?? ''
        : run['user_text']?.toString() ?? '';
    final status = (step['status']?.toString() ?? '').isNotEmpty
        ? step['status']?.toString() ?? ''
        : run['status']?.toString() ?? '';

    final evRaw = step['evidence'];
    final evidence = <Map<String, dynamic>>[];
    if (evRaw is List) {
      for (final item in evRaw) {
        if (item is Map) evidence.add(Map<String, dynamic>.from(item));
      }
    }

    bool? verified;
    final meta = step['meta'];
    if (meta is Map) {
      final v = meta['verification'];
      if (v is Map && v['ok'] is bool) verified = v['ok'] as bool;
    }

    final dot = _statusColor(status);
    final verifiedLabel = verified == null
        ? ''
        : (verified == true ? 'verified' : 'unverified');

    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: AppColors.surfaceStrong.withValues(alpha: 0.24),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.border.withValues(alpha: 0.4)),
      ),
      child: Row(
        children: [
          Container(
            width: 8,
            height: 8,
            decoration: BoxDecoration(color: dot, shape: BoxShape.circle),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  action.isNotEmpty ? action : 'run',
                  style: const TextStyle(
                    color: AppColors.textPrimary,
                    fontSize: 11,
                    fontWeight: FontWeight.w800,
                  ),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
                if (title.trim().isNotEmpty) ...[
                  const SizedBox(height: 4),
                  Text(
                    title,
                    style: const TextStyle(
                      color: AppColors.textMuted,
                      fontSize: 11,
                    ),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                ],
              ],
            ),
          ),
          const SizedBox(width: 10),
          Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Text(
                status.isNotEmpty ? status : '-',
                style: TextStyle(
                  color: dot,
                  fontSize: 10,
                  fontWeight: FontWeight.w900,
                ),
              ),
              if (verifiedLabel.isNotEmpty) ...[
                const SizedBox(height: 2),
                Text(
                  verifiedLabel,
                  style: TextStyle(
                    color: verified == true
                        ? AppColors.accentSoft
                        : AppColors.warning,
                    fontSize: 10,
                    fontWeight: FontWeight.w800,
                  ),
                ),
              ],
              if (evidence.isNotEmpty) ...[
                const SizedBox(height: 2),
                InkWell(
                  onTap: () => _showEvidenceDialog(context, evidence),
                  borderRadius: BorderRadius.circular(8),
                  child: Padding(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 6,
                      vertical: 2,
                    ),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        const Icon(
                          Icons.attach_file,
                          size: 14,
                          color: AppColors.textMuted,
                        ),
                        const SizedBox(width: 4),
                        Text(
                          '${evidence.length}',
                          style: const TextStyle(
                            color: AppColors.textMuted,
                            fontSize: 10,
                            fontWeight: FontWeight.w800,
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ],
            ],
          ),
        ],
      ),
    );
  }

  void _showEvidenceDialog(
    BuildContext context,
    List<Map<String, dynamic>> evidence,
  ) {
    showDialog<void>(
      context: context,
      builder: (context) {
        return AlertDialog(
          title: const Text('Evidence'),
          content: SizedBox(
            width: 520,
            child: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  for (final e in evidence)
                    _EvidenceRow(
                      kind: e['kind']?.toString() ?? 'item',
                      summary: e['summary']?.toString() ?? '',
                      value: e['value']?.toString() ?? '',
                    ),
                ],
              ),
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(context).pop(),
              child: const Text('Close'),
            ),
          ],
        );
      },
    );
  }
}

class _EvidenceRow extends StatelessWidget {
  final String kind;
  final String summary;
  final String value;

  const _EvidenceRow({
    required this.kind,
    required this.summary,
    required this.value,
  });

  bool get _isUrl =>
      value.startsWith('http://') || value.startsWith('https://');

  Future<void> _open() async {
    if (value.trim().isEmpty) return;
    try {
      if (_isUrl) {
        await Process.run('cmd', ['/c', 'start', '', value]);
        return;
      }

      final entity = FileSystemEntity.typeSync(value);
      if (entity == FileSystemEntityType.directory) {
        await Process.run('explorer', [value]);
        return;
      }
      await Process.run('explorer', ['/select,$value']);
    } catch (_) {
      // Best-effort only.
    }
  }

  Future<void> _copy(BuildContext context) async {
    if (value.trim().isEmpty) return;
    await Clipboard.setData(ClipboardData(text: value));
    if (!context.mounted) return;
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(const SnackBar(content: Text('Copied')));
  }

  @override
  Widget build(BuildContext context) {
    final label = summary.trim().isNotEmpty ? summary : kind;
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        color: AppColors.surfaceStrong.withValues(alpha: 0.22),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.border.withValues(alpha: 0.4)),
      ),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  label,
                  style: const TextStyle(
                    color: AppColors.textPrimary,
                    fontSize: 12,
                    fontWeight: FontWeight.w800,
                  ),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
                const SizedBox(height: 4),
                Text(
                  value,
                  style: const TextStyle(
                    color: AppColors.textMuted,
                    fontSize: 11,
                  ),
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                ),
              ],
            ),
          ),
          const SizedBox(width: 10),
          IconButton(
            tooltip: 'Copy',
            onPressed: () => _copy(context),
            icon: const Icon(
              Icons.copy_rounded,
              size: 18,
              color: AppColors.textMuted,
            ),
          ),
          IconButton(
            tooltip: _isUrl ? 'Open in browser' : 'Open in Explorer',
            onPressed: _open,
            icon: const Icon(
              Icons.open_in_new_rounded,
              size: 18,
              color: AppColors.accent,
            ),
          ),
        ],
      ),
    );
  }
}

class _MissingInputRow extends StatelessWidget {
  final String projectName;
  final String keyName;
  final VoidCallback onSet;

  const _MissingInputRow({
    required this.projectName,
    required this.keyName,
    required this.onSet,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: AppColors.surfaceStrong.withValues(alpha: 0.28),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.border.withValues(alpha: 0.45)),
      ),
      child: Row(
        children: [
          const Icon(
            Icons.vpn_key_outlined,
            size: 16,
            color: AppColors.warning,
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  projectName,
                  style: const TextStyle(
                    color: AppColors.textMuted,
                    fontSize: 10,
                    fontWeight: FontWeight.w700,
                  ),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
                const SizedBox(height: 2),
                Text(
                  keyName,
                  style: const TextStyle(
                    color: AppColors.textPrimary,
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                  ),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ],
            ),
          ),
          const SizedBox(width: 10),
          TextButton(
            onPressed: onSet,
            style: TextButton.styleFrom(foregroundColor: AppColors.accent),
            child: const Text(
              'Set',
              style: TextStyle(fontWeight: FontWeight.w800),
            ),
          ),
        ],
      ),
    );
  }
}

class _ProjectTile extends StatelessWidget {
  final Map<String, dynamic> project;
  final List<Map<String, dynamic>> steps;
  final int missingInputsCount;
  final Color statusColor;
  final Color Function(String status) stepStatusColor;
  final VoidCallback onPause;
  final VoidCallback onResume;
  final VoidCallback onCancel;

  const _ProjectTile({
    required this.project,
    required this.steps,
    required this.missingInputsCount,
    required this.statusColor,
    required this.stepStatusColor,
    required this.onPause,
    required this.onResume,
    required this.onCancel,
  });

  @override
  Widget build(BuildContext context) {
    final id = project['id']?.toString() ?? '';
    final name = project['name']?.toString() ?? id;
    final status = project['status']?.toString() ?? '';
    final completed = steps
        .where((s) => s['status']?.toString() == 'completed')
        .length;
    final total = steps.length;
    final progress = total == 0 ? '0/0' : '$completed/$total';

    final canPause = status == 'active';
    final canResume = status == 'paused';

    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      decoration: BoxDecoration(
        color: AppColors.surfaceStrong.withValues(alpha: 0.26),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.border.withValues(alpha: 0.45)),
      ),
      child: ExpansionTile(
        tilePadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
        collapsedIconColor: AppColors.textMuted,
        iconColor: AppColors.textMuted,
        title: Row(
          children: [
            Container(
              width: 8,
              height: 8,
              decoration: BoxDecoration(
                color: statusColor,
                shape: BoxShape.circle,
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Text(
                name,
                style: const TextStyle(
                  color: AppColors.textPrimary,
                  fontSize: 13,
                  fontWeight: FontWeight.w700,
                ),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
              ),
            ),
            const SizedBox(width: 8),
            _TinyBadge(label: progress, color: AppColors.textMuted),
            if (missingInputsCount > 0) ...[
              const SizedBox(width: 6),
              _TinyBadge(
                label: 'inputs:$missingInputsCount',
                color: AppColors.warning,
              ),
            ],
          ],
        ),
        subtitle: Text(
          status.isNotEmpty ? status : 'unknown',
          style: TextStyle(
            color: statusColor.withValues(alpha: 0.9),
            fontSize: 11,
            fontWeight: FontWeight.w700,
          ),
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
        ),
        trailing: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            IconButton(
              onPressed: canPause ? onPause : null,
              tooltip: 'Pause',
              icon: Icon(
                Icons.pause_circle_outline,
                size: 18,
                color: canPause ? AppColors.textPrimary : AppColors.border,
              ),
            ),
            IconButton(
              onPressed: canResume ? onResume : null,
              tooltip: 'Resume',
              icon: Icon(
                Icons.play_circle_outline,
                size: 18,
                color: canResume ? AppColors.textPrimary : AppColors.border,
              ),
            ),
            IconButton(
              onPressed: onCancel,
              tooltip: 'Cancel',
              icon: const Icon(
                Icons.stop_circle_outlined,
                size: 18,
                color: AppColors.textMuted,
              ),
            ),
          ],
        ),
        children: [
          if (steps.isEmpty)
            const Padding(
              padding: EdgeInsets.fromLTRB(12, 0, 12, 12),
              child: Text(
                'No steps',
                style: TextStyle(color: AppColors.textMuted, fontSize: 12),
              ),
            )
          else
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
              child: Column(
                children: [
                  for (final s in steps.take(6))
                    _StepRow(
                      order: (s['order_index'] as num?)?.toInt() ?? 0,
                      title:
                          s['title']?.toString() ??
                          s['id']?.toString() ??
                          'Step',
                      status: s['status']?.toString() ?? '',
                      color: stepStatusColor(s['status']?.toString() ?? ''),
                    ),
                  if (steps.length > 6)
                    const Padding(
                      padding: EdgeInsets.only(top: 6),
                      child: Align(
                        alignment: Alignment.centerLeft,
                        child: Text(
                          'More steps exist...',
                          style: TextStyle(
                            color: AppColors.textMuted,
                            fontSize: 11,
                          ),
                        ),
                      ),
                    ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}

class _StepRow extends StatelessWidget {
  final int order;
  final String title;
  final String status;
  final Color color;

  const _StepRow({
    required this.order,
    required this.title,
    required this.status,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        children: [
          Container(
            width: 22,
            height: 22,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: color.withValues(alpha: 0.14),
              borderRadius: BorderRadius.circular(8),
              border: Border.all(color: color.withValues(alpha: 0.25)),
            ),
            child: Text(
              '${order + 1}',
              style: TextStyle(
                color: color,
                fontSize: 10,
                fontWeight: FontWeight.w800,
              ),
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              title,
              style: const TextStyle(
                color: AppColors.textPrimary,
                fontSize: 12,
                fontWeight: FontWeight.w700,
              ),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
            ),
          ),
          const SizedBox(width: 8),
          _TinyBadge(
            label: status.isNotEmpty ? status : 'unknown',
            color: color,
          ),
        ],
      ),
    );
  }
}

class _TinyBadge extends StatelessWidget {
  final String label;
  final Color color;

  const _TinyBadge({required this.label, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: color.withValues(alpha: 0.22)),
      ),
      child: Text(
        label,
        style: TextStyle(
          color: color,
          fontSize: 10,
          fontWeight: FontWeight.w800,
        ),
      ),
    );
  }
}

class _ScheduledTaskRow extends StatelessWidget {
  final String name;
  final String nextRun;
  final VoidCallback onCancel;

  const _ScheduledTaskRow({
    required this.name,
    required this.nextRun,
    required this.onCancel,
  });

  String _formatLocal(String iso) {
    if (iso.trim().isEmpty) return 'Pending';
    try {
      return DateTime.parse(iso).toLocal().toString().substring(0, 16);
    } catch (_) {
      return iso;
    }
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: AppColors.surfaceStrong.withValues(alpha: 0.28),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.border.withValues(alpha: 0.45)),
      ),
      child: Row(
        children: [
          const Icon(Icons.schedule, size: 16, color: AppColors.accent),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  name,
                  style: const TextStyle(
                    color: AppColors.textPrimary,
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                  ),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
                const SizedBox(height: 2),
                Text(
                  _formatLocal(nextRun),
                  style: const TextStyle(
                    color: AppColors.textMuted,
                    fontSize: 11,
                  ),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ],
            ),
          ),
          const SizedBox(width: 10),
          IconButton(
            onPressed: onCancel,
            tooltip: 'Cancel task',
            icon: const Icon(
              Icons.delete_outline,
              size: 18,
              color: AppColors.textMuted,
            ),
          ),
        ],
      ),
    );
  }
}
