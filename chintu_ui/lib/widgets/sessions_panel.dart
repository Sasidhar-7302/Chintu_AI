import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../theme/app_theme.dart';
import '../services/websocket_service.dart';

class SessionsPanel extends StatefulWidget {
  const SessionsPanel({super.key});

  @override
  State<SessionsPanel> createState() => _SessionsPanelState();
}

class _SessionsPanelState extends State<SessionsPanel> {
  bool _showInternal = false;
  final Set<String> _typeFilters = {'main', 'group', 'cron', 'node'};
  final Set<String> _visibilityFilters = {'public', 'private', 'internal'};
  String _searchQuery = '';

  @override
  Widget build(BuildContext context) {
    return Consumer<WebSocketService>(
      builder: (context, ws, child) {
        final sessions = ws.sessions.where((s) {
          final visibility = (s['visibility'] ?? 'public').toString().toLowerCase();
          if (!_showInternal && visibility == 'internal') {
            return false;
          }
          if (!_visibilityFilters.contains(visibility)) {
            return false;
          }
          final type = (s['type'] ?? 'main').toString().toLowerCase();
          if (!_typeFilters.contains(type)) {
            return false;
          }
          if (_searchQuery.isNotEmpty) {
            final name = (s['name'] ?? s['id'] ?? '').toString().toLowerCase();
            if (!name.contains(_searchQuery)) {
              return false;
            }
          }
          return true;
        }).toList();
        final cronJobs = ws.cronJobs;

        return ListView(
          padding: const EdgeInsets.all(12),
          children: [
            Row(
              children: [
                _SectionHeader(title: 'Active Sessions', count: sessions.length),
                const Spacer(),
                Text(
                  'Show internal',
                  style: const TextStyle(color: AppColors.textMuted, fontSize: 11),
                ),
                Switch(
                  value: _showInternal,
                  onChanged: (val) => setState(() => _showInternal = val),
                ),
              ],
            ),
            const SizedBox(height: 6),
            TextField(
              decoration: const InputDecoration(
                hintText: 'Search sessions...',
                prefixIcon: Icon(Icons.search),
              ),
              onChanged: (val) => setState(() => _searchQuery = val.toLowerCase()),
            ),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              runSpacing: 6,
              children: [
                _filterChip('public', kind: 'visibility'),
                _filterChip('private', kind: 'visibility'),
                _filterChip('internal', kind: 'visibility'),
              ],
            ),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              runSpacing: 6,
              children: [
                _filterChip('main'),
                _filterChip('group'),
                _filterChip('cron'),
                _filterChip('node'),
              ],
            ),
            const SizedBox(height: 8),
            if (sessions.isEmpty)
              _emptyState('No active sessions')
            else
              ...sessions.map((s) => _SessionTile(session: s, ws: ws)),
            const SizedBox(height: 16),
            _SectionHeader(title: 'Cron Jobs', count: cronJobs.length),
            const SizedBox(height: 8),
            if (cronJobs.isEmpty)
              _emptyState('No cron jobs configured')
            else
              ...cronJobs.map((j) => _CronTile(job: j, ws: ws)),
          ],
        );
      },
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

  Widget _filterChip(String type, {String kind = 'type'}) {
    final active = kind == 'visibility'
        ? _visibilityFilters.contains(type)
        : _typeFilters.contains(type);
    return FilterChip(
      label: Text(type.toUpperCase()),
      selected: active,
      onSelected: (val) {
        setState(() {
          if (kind == 'visibility') {
            if (val) {
              _visibilityFilters.add(type);
            } else {
              _visibilityFilters.remove(type);
            }
          } else {
            if (val) {
              _typeFilters.add(type);
            } else {
              _typeFilters.remove(type);
            }
          }
        });
      },
    );
  }
}

class _SectionHeader extends StatelessWidget {
  final String title;
  final int count;
  const _SectionHeader({required this.title, required this.count});

  @override
  Widget build(BuildContext context) {
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
        const SizedBox(width: 8),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
          decoration: BoxDecoration(
            color: AppColors.accent.withValues(alpha: 0.15),
            borderRadius: BorderRadius.circular(10),
            border: Border.all(color: AppColors.accent.withValues(alpha: 0.3)),
          ),
          child: Text(
            count.toString(),
            style: const TextStyle(
              color: AppColors.textPrimary,
              fontSize: 10,
              fontWeight: FontWeight.w600,
            ),
          ),
        ),
      ],
    );
  }
}

class _SessionTile extends StatelessWidget {
  final Map<String, dynamic> session;
  final WebSocketService ws;
  const _SessionTile({required this.session, required this.ws});

  @override
  Widget build(BuildContext context) {
    final name = session['name'] ?? session['id'] ?? 'session';
    final type = (session['type'] ?? 'main').toString().toUpperCase();
    final visibility = (session['visibility'] ?? 'public').toString();
    final updatedAt = session['updated_at'] ?? '';
    final transcriptPath =
        session['transcript_path']?.toString() ?? '~/.chintu/sessions/${session['id']}/transcript.jsonl';

    return InkWell(
      onTap: () async {
        final sessionId = session['id']?.toString() ?? '';
        await ws.requestSessionHistory(sessionId, limit: 50);
        if (!context.mounted) return;
        showDialog(
          context: context,
          builder: (_) => _SessionDetailsDialog(
            sessionId: sessionId,
            transcriptPath: transcriptPath,
          ),
        );
      },
      child: Container(
        margin: const EdgeInsets.only(bottom: 8),
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: AppColors.surfaceStrong.withValues(alpha: 0.3),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: AppColors.border.withValues(alpha: 0.4)),
        ),
        child: Row(
          children: [
            Container(
              padding: const EdgeInsets.all(6),
              decoration: BoxDecoration(
                color: AppColors.accent.withValues(alpha: 0.1),
                borderRadius: BorderRadius.circular(8),
              ),
              child: const Icon(Icons.chat_bubble_outline, size: 16, color: AppColors.accent),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    name.toString(),
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
                    '$type - $visibility - $updatedAt',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(color: AppColors.textSecondary, fontSize: 11),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _CronTile extends StatelessWidget {
  final Map<String, dynamic> job;
  final WebSocketService ws;
  const _CronTile({required this.job, required this.ws});

  @override
  Widget build(BuildContext context) {
    final name = job['name'] ?? 'cron';
    final schedule = job['schedule'] ?? '';
    final nextRun = job['next_run'] ?? 'Pending';

    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppColors.surfaceStrong.withValues(alpha: 0.3),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.border.withValues(alpha: 0.4)),
      ),
      child: Row(
        children: [
          Container(
            padding: const EdgeInsets.all(6),
            decoration: BoxDecoration(
              color: AppColors.accentDeep.withValues(alpha: 0.12),
              borderRadius: BorderRadius.circular(8),
            ),
            child: const Icon(Icons.timer, size: 16, color: AppColors.accentDeep),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  name.toString(),
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
                  'Schedule: $schedule - Next: $nextRun',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(color: AppColors.textSecondary, fontSize: 11),
                ),
              ],
            ),
          ),
          Switch(
            value: (job['enabled'] ?? true) == true,
            onChanged: (val) {
              final id = job['id']?.toString() ?? '';
              if (id.isNotEmpty) {
                ws.updateCronJob(id, enabled: val);
              }
            },
          ),
          IconButton(
            icon: const Icon(Icons.stop_circle_outlined, size: 18, color: AppColors.textMuted),
            onPressed: () {
              final id = job['id']?.toString() ?? '';
              if (id.isNotEmpty) {
                ws.cancelCronJob(id);
              }
            },
            tooltip: 'Stop Cron Job',
          ),
          IconButton(
            icon: const Icon(Icons.edit, size: 18, color: AppColors.textMuted),
            onPressed: () {
              final id = job['id']?.toString() ?? '';
              if (id.isNotEmpty) {
                showDialog(
                  context: context,
                  builder: (_) => _CronEditDialog(job: job, ws: ws),
                );
              }
            },
            tooltip: 'Edit Cron Job',
          ),
        ],
      ),
    );
  }
}

class _SessionDetailsDialog extends StatelessWidget {
  final String sessionId;
  final String transcriptPath;
  const _SessionDetailsDialog({required this.sessionId, required this.transcriptPath});

  @override
  Widget build(BuildContext context) {
    return Dialog(
      insetPadding: const EdgeInsets.all(16),
      child: SizedBox(
        width: 520,
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Consumer<WebSocketService>(
            builder: (context, ws, child) {
              final history = ws.getSessionHistory(sessionId) ?? [];
              return Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      const Icon(Icons.article_outlined, color: AppColors.accent),
                      const SizedBox(width: 8),
                      Text(
                        'Session Details',
                        style: Theme.of(context).textTheme.titleSmall?.copyWith(
                              color: AppColors.textPrimary,
                              fontWeight: FontWeight.w600,
                            ),
                      ),
                      const Spacer(),
                      IconButton(
                        icon: const Icon(Icons.close, size: 18),
                        onPressed: () => Navigator.pop(context),
                      ),
                    ],
                  ),
                  const SizedBox(height: 6),
                  Text(
                    sessionId,
                    style: const TextStyle(color: AppColors.textMuted, fontSize: 11),
                  ),
                  const SizedBox(height: 8),
                  Row(
                    children: [
                      const Icon(Icons.folder_open, size: 16, color: AppColors.textMuted),
                      const SizedBox(width: 6),
                      Expanded(
                        child: Text(
                          'Path: $transcriptPath',
                          style: const TextStyle(color: AppColors.textMuted, fontSize: 11),
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                      IconButton(
                        icon: const Icon(Icons.copy, size: 16, color: AppColors.textMuted),
                        onPressed: () {
                          ws.copyToClipboard(transcriptPath);
                        },
                        tooltip: 'Copy path',
                      ),
                    ],
                  ),
                  const SizedBox(height: 12),
                  SizedBox(
                    height: 320,
                    child: history.isEmpty
                        ? const Center(
                            child: Text(
                              'No transcript available',
                              style: TextStyle(color: AppColors.textMuted, fontSize: 12),
                            ),
                          )
                        : ListView.separated(
                            itemCount: history.length,
                            separatorBuilder: (_, __) => const Divider(height: 16),
                            itemBuilder: (_, index) {
                              final item = history[index];
                              final role = item['role'] ?? 'unknown';
                              final content = item['content'] ?? '';
                              final ts = item['ts'] ?? '';
                              return Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    '$role - $ts',
                                    style: const TextStyle(
                                      color: AppColors.textMuted,
                                      fontSize: 10,
                                      fontWeight: FontWeight.w600,
                                    ),
                                  ),
                                  const SizedBox(height: 4),
                                  Text(
                                    content.toString(),
                                    style: const TextStyle(
                                      color: AppColors.textPrimary,
                                      fontSize: 12,
                                    ),
                                  ),
                                ],
                              );
                            },
                          ),
                  ),
                ],
              );
            },
          ),
        ),
      ),
    );
  }
}

class _CronEditDialog extends StatefulWidget {
  final Map<String, dynamic> job;
  final WebSocketService ws;
  const _CronEditDialog({required this.job, required this.ws});

  @override
  State<_CronEditDialog> createState() => _CronEditDialogState();
}

class _CronEditDialogState extends State<_CronEditDialog> {
  late final TextEditingController _nameController;
  late final TextEditingController _scheduleController;

  @override
  void initState() {
    super.initState();
    _nameController = TextEditingController(text: widget.job['name']?.toString() ?? '');
    _scheduleController = TextEditingController(text: widget.job['schedule']?.toString() ?? '');
  }

  @override
  void dispose() {
    _nameController.dispose();
    _scheduleController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final id = widget.job['id']?.toString() ?? '';
    return Dialog(
      insetPadding: const EdgeInsets.all(16),
      child: SizedBox(
        width: 420,
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Row(
                children: [
                  const Icon(Icons.edit, color: AppColors.accent),
                  const SizedBox(width: 8),
                  Text(
                    'Edit Cron Job',
                    style: Theme.of(context).textTheme.titleSmall?.copyWith(
                          color: AppColors.textPrimary,
                          fontWeight: FontWeight.w600,
                        ),
                  ),
                  const Spacer(),
                  IconButton(
                    icon: const Icon(Icons.close, size: 18),
                    onPressed: () => Navigator.pop(context),
                  ),
                ],
              ),
              const SizedBox(height: 8),
              TextField(
                controller: _nameController,
                decoration: const InputDecoration(labelText: 'Name'),
              ),
              const SizedBox(height: 8),
              TextField(
                controller: _scheduleController,
                decoration: const InputDecoration(labelText: 'Schedule (cron or every 10m)'),
              ),
              const SizedBox(height: 16),
              Row(
                children: [
                  const Spacer(),
                  TextButton(
                    onPressed: () => Navigator.pop(context),
                    child: const Text('Cancel'),
                  ),
                  const SizedBox(width: 8),
                  ElevatedButton(
                    onPressed: () {
                      final name = _nameController.text.trim();
                      final schedule = _scheduleController.text.trim();
                    if (id.isNotEmpty) {
                      if (schedule.isNotEmpty) {
                        widget.ws.updateCronJob(id, schedule: schedule);
                      }
                      if (name.isNotEmpty) {
                        widget.ws.updateCronJob(id, name: name);
                      }
                    }
                      Navigator.pop(context);
                    },
                    child: const Text('Save'),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

