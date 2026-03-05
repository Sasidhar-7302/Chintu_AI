import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../services/websocket_service.dart';
import '../theme/app_theme.dart';

class DashboardPanel extends StatefulWidget {
  final VoidCallback? onClose;

  const DashboardPanel({super.key, this.onClose});

  @override
  State<DashboardPanel> createState() => _DashboardPanelState();
}

class _DashboardPanelState extends State<DashboardPanel> {
  final TextEditingController _memoryController = TextEditingController();
  final TextEditingController _calendarCredentialsController =
      TextEditingController();
  final TextEditingController _emailHostController = TextEditingController();
  final TextEditingController _emailPortController = TextEditingController();
  final TextEditingController _emailUserController = TextEditingController();
  final TextEditingController _emailFolderController = TextEditingController();
  final TextEditingController _emailPasswordController =
      TextEditingController();
  final TextEditingController _oauthCredentialsPathController =
      TextEditingController();
  String _selectedRunId = '';
  String _oauthProvider = 'google_calendar';
  bool _oauthWriteAccess = false;
  bool _oauthForceReauth = false;
  bool _oauthRemoveCredentials = false;

  @override
  void dispose() {
    _memoryController.dispose();
    _calendarCredentialsController.dispose();
    _emailHostController.dispose();
    _emailPortController.dispose();
    _emailUserController.dispose();
    _emailFolderController.dispose();
    _emailPasswordController.dispose();
    _oauthCredentialsPathController.dispose();
    super.dispose();
  }

  Color _statusColor(String status) {
    switch (status) {
      case 'running':
        return AppColors.accent;
      case 'queued':
        return AppColors.accentSoft;
      case 'waiting_approval':
      case 'waiting_input':
        return AppColors.warning;
      case 'completed':
        return AppColors.success;
      case 'failed':
      case 'timed_out':
        return AppColors.danger;
      case 'paused':
        return AppColors.warning;
      case 'cancelled':
        return AppColors.textMuted;
      default:
        return AppColors.textMuted;
    }
  }

  Future<void> _openProviderKeyDialog(
    WebSocketService ws, {
    required String providerLabel,
    required String providerKey,
  }) async {
    final controller = TextEditingController();
    final key = await showDialog<String>(
      context: context,
      builder: (ctx) {
        return AlertDialog(
          backgroundColor: AppColors.surface,
          title: Text(
            'Set $providerLabel API Key',
            style: const TextStyle(
              color: AppColors.textPrimary,
              fontWeight: FontWeight.w800,
              fontSize: 13,
            ),
          ),
          content: TextField(
            controller: controller,
            obscureText: true,
            decoration: const InputDecoration(hintText: 'Paste API key...'),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(ctx).pop(null),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () => Navigator.of(ctx).pop(controller.text),
              child: const Text('Save'),
            ),
          ],
        );
      },
    );
    final trimmed = (key ?? '').trim();
    if (trimmed.isEmpty) return;
    ws.saveProviderApiKey(provider: providerKey, apiKey: trimmed);
  }

  Widget _panel({required Widget child}) {
    return Container(
      decoration: BoxDecoration(
        color: AppColors.surface.withValues(alpha: 0.94),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppColors.border),
      ),
      child: child,
    );
  }

  Widget _sectionTitle(String text, {String? count}) {
    return Row(
      children: [
        Text(
          text,
          style: const TextStyle(
            fontSize: 12,
            fontWeight: FontWeight.w800,
            color: AppColors.textPrimary,
          ),
        ),
        const Spacer(),
        if (count != null)
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
            decoration: BoxDecoration(
              color: AppColors.surfaceElevated,
              borderRadius: BorderRadius.circular(999),
              border: Border.all(color: AppColors.border),
            ),
            child: Text(
              count,
              style: const TextStyle(
                fontSize: 10.5,
                color: AppColors.textMuted,
              ),
            ),
          ),
      ],
    );
  }

  Widget _tabHint(String text) {
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        color: AppColors.surfaceElevated.withValues(alpha: 0.75),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: AppColors.border.withValues(alpha: 0.9)),
      ),
      child: Text(
        text,
        style: const TextStyle(
          color: AppColors.textMuted,
          fontSize: 11,
          fontWeight: FontWeight.w600,
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Consumer<WebSocketService>(
      builder: (context, ws, child) {
        final connected = ws.isConnected;
        final runs = _runsFromSnapshot(ws);
        if (_selectedRunId.isEmpty && runs.isNotEmpty) {
          _selectedRunId = runs.first['id']?.toString() ?? '';
        }

        return _panel(
          child: DefaultTabController(
            length: 8,
            child: Column(
              children: [
                Padding(
                  padding: const EdgeInsets.fromLTRB(14, 12, 10, 8),
                  child: Row(
                    children: [
                      const Text(
                        'Operations',
                        style: TextStyle(
                          fontSize: 13,
                          fontWeight: FontWeight.w800,
                          color: AppColors.textPrimary,
                        ),
                      ),
                      const SizedBox(width: 10),
                      _pill(
                        connected ? 'connected' : 'disconnected',
                        connected ? AppColors.accent : AppColors.danger,
                      ),
                      const Spacer(),
                      if (widget.onClose != null)
                        IconButton(
                          onPressed: widget.onClose,
                          icon: const Icon(Icons.close, size: 18),
                          color: AppColors.textMuted,
                          tooltip: 'Close',
                        ),
                    ],
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(12, 0, 12, 8),
                  child: Row(
                    children: [
                      _pill('runs ${runs.length}', AppColors.textMuted),
                      const SizedBox(width: 6),
                      _pill(
                        'approvals ${ws.pendingCodeApprovals.length + ws.orchestratorApprovals.where((a) => (a['status']?.toString() ?? '') == 'pending').length}',
                        AppColors.warning,
                      ),
                      const SizedBox(width: 6),
                      _pill(
                        'memory ${ws.memoryResults.length}',
                        AppColors.accentSoft,
                      ),
                    ],
                  ),
                ),
                const Divider(height: 1, color: AppColors.border),
                const TabBar(
                  isScrollable: true,
                  dividerColor: Colors.transparent,
                  labelColor: AppColors.accent,
                  unselectedLabelColor: AppColors.textMuted,
                  indicatorColor: AppColors.accent,
                  indicatorSize: TabBarIndicatorSize.tab,
                  tabs: [
                    Tab(text: 'Tasks'),
                    Tab(text: 'Review'),
                    Tab(text: 'Memory'),
                    Tab(text: 'Models'),
                    Tab(text: 'Identity'),
                    Tab(text: 'Schedule'),
                    Tab(text: 'Links'),
                    Tab(text: 'Proof'),
                  ],
                ),
                const Divider(height: 1, color: AppColors.border),
                Expanded(
                  child: TabBarView(
                    children: [
                      _runsTab(ws, runs),
                      _approvalsTab(ws),
                      _memoryTab(ws),
                      _modelsTab(ws),
                      _identityTab(ws),
                      _scheduleTab(context, ws),
                      _integrationsTab(ws),
                      _evidenceTab(ws, runs),
                    ],
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }

  String _prettyJson(dynamic value) {
    try {
      return const JsonEncoder.withIndent('  ').convert(value);
    } catch (_) {
      return (value ?? '').toString();
    }
  }

  Widget _modelsTab(WebSocketService ws) {
    final integrations = ws.integrations;
    final providers = (integrations['providers'] is Map)
        ? Map<String, dynamic>.from(integrations['providers'])
        : <String, dynamic>{};
    final rows = <Map<String, dynamic>>[
      {'name': 'NVIDIA', 'raw': providers['nvidia']},
      {'name': 'Groq', 'raw': providers['groq']},
      {'name': 'Gemini', 'raw': providers['gemini']},
      {'name': 'DeepSeek', 'raw': providers['deepseek']},
    ];

    return ListView(
      padding: const EdgeInsets.all(12),
      children: [
        _tabHint(
          'Model routing health, provider key state, and active execution metadata.',
        ),
        _sectionTitle('Model Runtime'),
        const SizedBox(height: 10),
        Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(14),
            color: AppColors.surfaceStrong.withValues(alpha: 0.58),
            border: Border.all(color: AppColors.border.withValues(alpha: 0.72)),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Last model: ${ws.lastModel.isEmpty ? '-' : ws.lastModel}',
                style: const TextStyle(
                  color: AppColors.textPrimary,
                  fontSize: 12,
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(height: 6),
              Text(
                'Last capability: ${ws.lastCapability.isEmpty ? '-' : ws.lastCapability}',
                style: const TextStyle(
                  color: AppColors.textMuted,
                  fontSize: 11,
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 12),
        _sectionTitle('Provider Key State'),
        const SizedBox(height: 10),
        for (final row in rows)
          Builder(
            builder: (context) {
              final name = row['name']?.toString() ?? 'Provider';
              final raw = row['raw'];
              final data = raw is Map
                  ? Map<String, dynamic>.from(raw)
                  : <String, dynamic>{};
              final hasKey = data['api_key_set'] == true;
              return Container(
                margin: const EdgeInsets.only(bottom: 8),
                padding: const EdgeInsets.symmetric(
                  horizontal: 10,
                  vertical: 10,
                ),
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(12),
                  color: Colors.black.withValues(alpha: 0.22),
                  border: Border.all(
                    color: AppColors.border.withValues(alpha: 0.62),
                  ),
                ),
                child: Row(
                  children: [
                    Text(
                      name,
                      style: const TextStyle(
                        fontSize: 11,
                        color: AppColors.textPrimary,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    const Spacer(),
                    _pill(
                      hasKey ? 'key set' : 'missing',
                      hasKey ? AppColors.success : AppColors.textMuted,
                    ),
                  ],
                ),
              );
            },
          ),
      ],
    );
  }

  Widget _identityTab(WebSocketService ws) {
    final integrations = ws.integrations;
    final calendar = (integrations['google_calendar'] is Map)
        ? Map<String, dynamic>.from(integrations['google_calendar'])
        : <String, dynamic>{};
    final email = (integrations['email_imap'] is Map)
        ? Map<String, dynamic>.from(integrations['email_imap'])
        : <String, dynamic>{};
    final calendarConfigured = calendar['configured'] == true;
    final emailConfigured = email['configured'] == true;
    final activeIntegrations = [calendarConfigured, emailConfigured]
        .where((v) => v)
        .length;
    final sid = ws.sessionId ?? '';

    return ListView(
      padding: const EdgeInsets.all(12),
      children: [
        _tabHint(
          'Identity and trust boundaries: owner controls, session details, and connected account posture.',
        ),
        _sectionTitle('Identity Runtime'),
        const SizedBox(height: 10),
        Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(14),
            color: AppColors.surfaceStrong.withValues(alpha: 0.58),
            border: Border.all(color: AppColors.border.withValues(alpha: 0.72)),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                ws.isConnected ? 'Gateway: connected' : 'Gateway: disconnected',
                style: TextStyle(
                  color: ws.isConnected ? AppColors.success : AppColors.danger,
                  fontSize: 12,
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(height: 6),
              Text(
                'Session ID: ${sid.isEmpty ? '-' : sid}',
                style: const TextStyle(
                  color: AppColors.textMuted,
                  fontSize: 11,
                ),
              ),
              const SizedBox(height: 6),
              Text(
                'Configured integrations: $activeIntegrations / 2',
                style: const TextStyle(
                  color: AppColors.textMuted,
                  fontSize: 11,
                ),
              ),
              const SizedBox(height: 10),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  _pill(
                    calendarConfigured ? 'calendar linked' : 'calendar missing',
                    calendarConfigured ? AppColors.success : AppColors.warning,
                  ),
                  _pill(
                    emailConfigured ? 'email linked' : 'email missing',
                    emailConfigured ? AppColors.success : AppColors.warning,
                  ),
                  _pill('owner-gated remote ops', AppColors.accentSoft),
                ],
              ),
              if (sid.isNotEmpty) ...[
                const SizedBox(height: 10),
                OutlinedButton.icon(
                  onPressed: () {
                    Clipboard.setData(ClipboardData(text: sid));
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(content: Text('Session ID copied')),
                    );
                  },
                  icon: const Icon(Icons.copy_rounded, size: 16),
                  label: const Text('Copy Session ID'),
                ),
              ],
            ],
          ),
        ),
      ],
    );
  }

  Widget _integrationsTab(WebSocketService ws) {
    final integrations = ws.integrations;
    final lastResult = ws.integrationsLastResult;
    final lastMsg = lastResult['message']?.toString() ?? '';
    final lastOk = lastResult['ok'] == true;
    final calendar = (integrations['google_calendar'] is Map)
        ? Map<String, dynamic>.from(integrations['google_calendar'])
        : <String, dynamic>{};
    final email = (integrations['email_imap'] is Map)
        ? Map<String, dynamic>.from(integrations['email_imap'])
        : <String, dynamic>{};
    final providers = (integrations['providers'] is Map)
        ? Map<String, dynamic>.from(integrations['providers'])
        : <String, dynamic>{};

    final calAvailable = calendar['available'] == true;
    final calConfigured = calendar['configured'] == true;
    final calTokenValid = calendar['token_valid'] == true;
    final calWriteAccess = calendar['write_access'] == true;

    final emailEnabled = email['enabled'] == true;
    final emailConfigured = email['configured'] == true;
    final emailHost = email['host']?.toString() ?? '';
    final emailPort = email['port']?.toString() ?? '993';
    final emailUserMasked = email['user_masked']?.toString() ?? '';
    final emailFolder = email['folder']?.toString() ?? 'INBOX';

    final googleCredPath = calendar['credentials_path']?.toString() ?? '';
    final googleTokenPath = calendar['token_path']?.toString() ?? '';
    final actionName = lastResult['action']?.toString() ?? '';
    final actionProvider = lastResult['provider']?.toString() ?? '';
    final actionOp = lastResult['operation']?.toString() ?? '';
    final actionDetails = lastResult['details'];

    if (_oauthProvider == 'google_calendar' && _oauthCredentialsPathController.text.trim().isEmpty) {
      _oauthCredentialsPathController.text = googleCredPath;
    }
    if (_oauthProvider == 'google_calendar' && calWriteAccess && !_oauthWriteAccess) {
      _oauthWriteAccess = true;
    }

    if (_emailHostController.text.trim().isEmpty && emailHost.isNotEmpty) {
      _emailHostController.text = emailHost;
    }
    if (_emailPortController.text.trim().isEmpty && emailPort.isNotEmpty) {
      _emailPortController.text = emailPort;
    }
    if (_emailFolderController.text.trim().isEmpty && emailFolder.isNotEmpty) {
      _emailFolderController.text = emailFolder;
    }

    Widget card(Widget child) {
      return Container(
        margin: const EdgeInsets.only(bottom: 12),
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(14),
          color: AppColors.surfaceStrong.withValues(alpha: 0.58),
          border: Border.all(color: AppColors.border.withValues(alpha: 0.72)),
        ),
        child: child,
      );
    }

    Widget statusPill(String label, bool ok) =>
        _pill(label, ok ? AppColors.success : AppColors.textMuted);

    return ListView(
      padding: const EdgeInsets.all(12),
      children: [
        _tabHint(
          'Configure OAuth/API keys and verify connectivity before running workflows that depend on external services.',
        ),
        Row(
          children: [
            const Text(
              'Integrations',
              style: TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w800,
                color: AppColors.textPrimary,
              ),
            ),
            const Spacer(),
            OutlinedButton(
              onPressed: ws.requestIntegrationsSnapshot,
              child: const Text('Refresh'),
            ),
          ],
        ),
        const SizedBox(height: 10),
        if (lastMsg.isNotEmpty)
          Container(
            margin: const EdgeInsets.only(bottom: 12),
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(14),
              color: (lastOk ? AppColors.success : AppColors.danger).withValues(
                alpha: 0.10,
              ),
              border: Border.all(
                color: (lastOk ? AppColors.success : AppColors.danger)
                    .withValues(alpha: 0.35),
              ),
            ),
            child: Text(
              lastMsg,
              style: TextStyle(
                fontSize: 11,
                color: lastOk ? AppColors.success : AppColors.danger,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),

        card(
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  const Text(
                    'OAuth Control Center',
                    style: TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.w800,
                      color: AppColors.textPrimary,
                    ),
                  ),
                  const Spacer(),
                  _pill(
                    _oauthProvider == 'google_calendar'
                        ? 'supported'
                        : 'planned',
                    _oauthProvider == 'google_calendar'
                        ? AppColors.success
                        : AppColors.warning,
                  ),
                ],
              ),
              const SizedBox(height: 10),
              const Text(
                'Use this panel for OAuth lifecycle actions (wizard, health, connect, revoke). '
                'Google Calendar is active now; other providers are staged as future options.',
                style: TextStyle(fontSize: 11, color: AppColors.textMuted),
              ),
              const SizedBox(height: 10),
              DropdownButtonFormField<String>(
                initialValue: _oauthProvider,
                decoration: const InputDecoration(
                  labelText: 'OAuth Provider',
                  hintText: 'Select provider',
                ),
                items: const [
                  DropdownMenuItem(value: 'google_calendar', child: Text('Google Calendar (active)')),
                  DropdownMenuItem(value: 'google_drive', child: Text('Google Drive (planned)')),
                  DropdownMenuItem(value: 'gmail', child: Text('Gmail (planned)')),
                  DropdownMenuItem(value: 'youtube', child: Text('YouTube (planned)')),
                  DropdownMenuItem(value: 'github', child: Text('GitHub (planned)')),
                  DropdownMenuItem(value: 'slack', child: Text('Slack (planned)')),
                  DropdownMenuItem(value: 'notion', child: Text('Notion (planned)')),
                ],
                onChanged: (value) {
                  final next = (value ?? '').trim();
                  if (next.isEmpty) return;
                  setState(() {
                    _oauthProvider = next;
                  });
                },
              ),
              const SizedBox(height: 10),
              TextField(
                controller: _oauthCredentialsPathController,
                decoration: const InputDecoration(
                  hintText: 'credentials.json path (optional for connect)',
                ),
              ),
              const SizedBox(height: 8),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  FilterChip(
                    label: const Text('Write access'),
                    selected: _oauthWriteAccess,
                    onSelected: _oauthProvider == 'google_calendar'
                        ? (value) => setState(() => _oauthWriteAccess = value)
                        : null,
                  ),
                  FilterChip(
                    label: const Text('Force reauth'),
                    selected: _oauthForceReauth,
                    onSelected: _oauthProvider == 'google_calendar'
                        ? (value) => setState(() => _oauthForceReauth = value)
                        : null,
                  ),
                  FilterChip(
                    label: const Text('Remove credentials on revoke'),
                    selected: _oauthRemoveCredentials,
                    onSelected: _oauthProvider == 'google_calendar'
                        ? (value) => setState(() => _oauthRemoveCredentials = value)
                        : null,
                  ),
                ],
              ),
              const SizedBox(height: 10),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  OutlinedButton(
                    onPressed: () => ws.requestOAuthAction(
                      provider: _oauthProvider,
                      operation: 'wizard',
                      writeAccess: _oauthWriteAccess,
                    ),
                    child: const Text('Wizard'),
                  ),
                  OutlinedButton(
                    onPressed: () => ws.requestOAuthAction(
                      provider: _oauthProvider,
                      operation: 'health',
                    ),
                    child: const Text('Health'),
                  ),
                  FilledButton(
                    onPressed: _oauthProvider == 'google_calendar'
                        ? () => ws.requestOAuthAction(
                              provider: _oauthProvider,
                              operation: 'connect',
                              writeAccess: _oauthWriteAccess,
                              forceReauth: _oauthForceReauth,
                              credentialsPath: _oauthCredentialsPathController.text,
                            )
                        : null,
                    child: const Text('Connect'),
                  ),
                  OutlinedButton(
                    onPressed: _oauthProvider == 'google_calendar'
                        ? () => ws.requestOAuthAction(
                              provider: _oauthProvider,
                              operation: 'revoke',
                              removeCredentials: _oauthRemoveCredentials,
                            )
                        : null,
                    child: const Text('Revoke'),
                  ),
                ],
              ),
              if (actionName == 'oauth_action' && actionProvider.isNotEmpty) ...[
                const SizedBox(height: 10),
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(10),
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(10),
                    color: Colors.black.withValues(alpha: 0.22),
                    border: Border.all(color: AppColors.border.withValues(alpha: 0.6)),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'Last OAuth action: $actionProvider / $actionOp',
                        style: const TextStyle(
                          fontSize: 10.5,
                          color: AppColors.textMuted,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                      const SizedBox(height: 6),
                      SelectableText(
                        _prettyJson(actionDetails),
                        style: const TextStyle(
                          fontSize: 10.5,
                          color: AppColors.textPrimary,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ],
          ),
        ),

        card(
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  const Text(
                    'Google Calendar',
                    style: TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.w800,
                      color: AppColors.textPrimary,
                    ),
                  ),
                  const Spacer(),
                  statusPill('available', calAvailable),
                  const SizedBox(width: 8),
                  statusPill('configured', calConfigured),
                  const SizedBox(width: 8),
                  statusPill('token', calTokenValid),
                ],
              ),
              const SizedBox(height: 10),
              Text(
                calAvailable
                    ? 'Save credentials.json once, then run Authenticate to link Calendar.'
                    : 'Calendar SDK missing on backend. Install google-api-python-client and google-auth-oauthlib.',
                style: const TextStyle(
                  fontSize: 11,
                  color: AppColors.textMuted,
                ),
              ),
              const SizedBox(height: 10),
              if (googleCredPath.isNotEmpty)
                Text(
                  'credentials: $googleCredPath',
                  style: const TextStyle(
                    fontSize: 10,
                    color: AppColors.textMuted,
                  ),
                ),
              if (googleTokenPath.isNotEmpty)
                Text(
                  'token: $googleTokenPath',
                  style: const TextStyle(
                    fontSize: 10,
                    color: AppColors.textMuted,
                  ),
                ),
              const SizedBox(height: 10),
              TextField(
                controller: _calendarCredentialsController,
                maxLines: 5,
                decoration: const InputDecoration(
                  hintText: 'Paste credentials JSON here...',
                ),
              ),
              const SizedBox(height: 10),
              Row(
                children: [
                  FilledButton(
                    onPressed: calAvailable
                        ? () {
                            ws.saveGoogleCalendarCredentials(
                              _calendarCredentialsController.text,
                            );
                            _calendarCredentialsController.text = '';
                          }
                        : null,
                    child: const Text('Save'),
                  ),
                  const SizedBox(width: 10),
                  OutlinedButton(
                    onPressed: (calAvailable && calConfigured)
                        ? ws.authenticateGoogleCalendar
                        : null,
                    child: const Text('Authenticate'),
                  ),
                ],
              ),
            ],
          ),
        ),

        card(
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  const Text(
                    'Email (IMAP)',
                    style: TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.w800,
                      color: AppColors.textPrimary,
                    ),
                  ),
                  const Spacer(),
                  statusPill('enabled', emailEnabled),
                  const SizedBox(width: 8),
                  statusPill('configured', emailConfigured),
                ],
              ),
              const SizedBox(height: 10),
              Text(
                'Host and username stay local. Password is stored in Identity Vault only.',
                style: const TextStyle(
                  fontSize: 11,
                  color: AppColors.textMuted,
                ),
              ),
              if (emailUserMasked.isNotEmpty) ...[
                const SizedBox(height: 6),
                Text(
                  'current user: $emailUserMasked',
                  style: const TextStyle(
                    fontSize: 10,
                    color: AppColors.textMuted,
                  ),
                ),
              ],
              const SizedBox(height: 10),
              TextField(
                controller: _emailHostController,
                decoration: const InputDecoration(
                  hintText: 'IMAP host (e.g. imap.gmail.com)',
                ),
              ),
              const SizedBox(height: 10),
              Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: _emailPortController,
                      decoration: const InputDecoration(
                        hintText: 'Port (default 993)',
                      ),
                      keyboardType: TextInputType.number,
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: TextField(
                      controller: _emailFolderController,
                      decoration: const InputDecoration(
                        hintText: 'Folder (INBOX)',
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 10),
              TextField(
                controller: _emailUserController,
                decoration: const InputDecoration(hintText: 'Email/username'),
              ),
              const SizedBox(height: 10),
              TextField(
                controller: _emailPasswordController,
                obscureText: true,
                decoration: const InputDecoration(
                  hintText: 'App password / IMAP password',
                ),
              ),
              const SizedBox(height: 10),
              Row(
                children: [
                  FilledButton(
                    onPressed: emailEnabled
                        ? () {
                            final port =
                                int.tryParse(
                                  _emailPortController.text.trim(),
                                ) ??
                                993;
                            ws.saveEmailImapConfig(
                              host: _emailHostController.text,
                              port: port,
                              user: _emailUserController.text,
                              folder: _emailFolderController.text,
                              password: _emailPasswordController.text,
                            );
                            // Clear password field after sending (best-effort).
                            _emailPasswordController.text = '';
                          }
                        : null,
                    child: const Text('Save'),
                  ),
                  const SizedBox(width: 10),
                  OutlinedButton(
                    onPressed: emailEnabled ? ws.testEmailImapConnection : null,
                    child: const Text('Test'),
                  ),
                ],
              ),
            ],
          ),
        ),

        card(
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'Provider Keys',
                style: TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w800,
                  color: AppColors.textPrimary,
                ),
              ),
              const SizedBox(height: 8),
              _providerRow(ws, 'NVIDIA', 'nvidia', providers['nvidia']),
              _providerRow(ws, 'Groq', 'groq', providers['groq']),
              _providerRow(ws, 'Gemini', 'gemini', providers['gemini']),
              _providerRow(ws, 'DeepSeek', 'deepseek', providers['deepseek']),
            ],
          ),
        ),
      ],
    );
  }

  Widget _providerRow(
    WebSocketService ws,
    String name,
    String key,
    dynamic raw,
  ) {
    final data = raw is Map
        ? Map<String, dynamic>.from(raw)
        : <String, dynamic>{};
    final has = data['api_key_set'] == true;
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 10),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(12),
        color: Colors.black.withValues(alpha: 0.22),
        border: Border.all(color: AppColors.border.withValues(alpha: 0.62)),
      ),
      child: Row(
        children: [
          Text(
            name,
            style: const TextStyle(
              fontSize: 11,
              color: AppColors.textPrimary,
              fontWeight: FontWeight.w700,
            ),
          ),
          const Spacer(),
          _pill(
            has ? 'key set' : 'missing',
            has ? AppColors.success : AppColors.textMuted,
          ),
          const SizedBox(width: 10),
          OutlinedButton(
            onPressed: () => _openProviderKeyDialog(
              ws,
              providerLabel: name,
              providerKey: key,
            ),
            child: Text(has ? 'Update' : 'Set'),
          ),
        ],
      ),
    );
  }

  Widget _pill(String text, Color color) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(999),
        color: color.withValues(alpha: 0.12),
        border: Border.all(color: color.withValues(alpha: 0.28)),
      ),
      child: Text(
        text,
        style: TextStyle(
          fontSize: 10,
          fontWeight: FontWeight.w700,
          color: color,
        ),
      ),
    );
  }

  List<Map<String, dynamic>> _runsFromSnapshot(WebSocketService ws) {
    final raw = ws.runsSnapshot['runs'];
    if (raw is List) {
      return raw.map((e) => Map<String, dynamic>.from(e)).toList();
    }
    return const [];
  }

  Widget _runsTab(WebSocketService ws, List<Map<String, dynamic>> runs) {
    return ListView(
      padding: const EdgeInsets.all(12),
      children: [
        _tabHint(
          'Open any run to inspect status, receipts, and evidence trail.',
        ),
        _sectionTitle('Recent Runs', count: '${runs.length}'),
        const SizedBox(height: 10),
        if (runs.isEmpty)
          const Text(
            'No runs yet.',
            style: TextStyle(color: AppColors.textMuted),
          ),
        for (final run in runs) _runRow(ws, run),
      ],
    );
  }

  Widget _runRow(WebSocketService ws, Map<String, dynamic> run) {
    final id = run['id']?.toString() ?? '';
    final status = run['status']?.toString() ?? '';
    final title = run['user_text']?.toString() ?? '';
    final createdAt = run['created_at']?.toString() ?? '';
    final color = _statusColor(status);

    return InkWell(
      onTap: () {
        setState(() => _selectedRunId = id);
        ws.requestRunReceipt(id);
      },
      borderRadius: BorderRadius.circular(14),
      child: Container(
        margin: const EdgeInsets.only(bottom: 10),
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(14),
          color: AppColors.surfaceStrong.withValues(alpha: 0.58),
          border: Border.all(color: AppColors.border.withValues(alpha: 0.72)),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(
              width: 10,
              height: 10,
              margin: const EdgeInsets.only(top: 4),
              decoration: BoxDecoration(
                color: color,
                borderRadius: BorderRadius.circular(99),
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    title.isEmpty ? '(no title)' : title,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.w700,
                      color: AppColors.textPrimary,
                    ),
                  ),
                  const SizedBox(height: 6),
                  Text(
                    '$status | ${_shortId(id)} | $createdAt',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontSize: 10,
                      color: AppColors.textMuted,
                    ),
                  ),
                ],
              ),
            ),
            if (id.isNotEmpty &&
                (status == 'running' ||
                    status == 'queued' ||
                    status == 'waiting_approval' ||
                    status == 'waiting_input'))
              IconButton(
                onPressed: () => ws.cancelRun(id),
                icon: const Icon(Icons.stop_circle_outlined, size: 18),
                tooltip: 'Cancel run',
                color: AppColors.danger,
              ),
          ],
        ),
      ),
    );
  }

  String _shortId(String id) {
    final s = id.trim();
    if (s.length <= 10) return s;
    return s.substring(0, 10);
  }

  Widget _approvalsTab(WebSocketService ws) {
    final pending = ws.hud['pending'];
    final pendingCap =
        (pending is Map) && (pending['capability_pending'] == true);
    final orchApprovals = ws.orchestratorApprovals
        .where((a) => (a['status']?.toString() ?? '') == 'pending')
        .toList();
    final codeApprovals = ws.pendingCodeApprovals;

    return ListView(
      padding: const EdgeInsets.all(12),
      children: [
        _tabHint(
          'Approve only when task intent, target scope, and diff all match your request.',
        ),
        _sectionTitle('Pending Capability'),
        const SizedBox(height: 8),
        if (!pendingCap)
          const Text('None', style: TextStyle(color: AppColors.textMuted))
        else
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: AppColors.surfaceStrong.withValues(alpha: 0.58),
              borderRadius: BorderRadius.circular(14),
              border: Border.all(
                color: AppColors.border.withValues(alpha: 0.72),
              ),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  pending['capability_pending_capability']?.toString() ?? '',
                  style: const TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w800,
                    color: AppColors.textPrimary,
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  pending['capability_pending_message']?.toString() ?? '',
                  style: const TextStyle(
                    fontSize: 11,
                    color: AppColors.textMuted,
                  ),
                ),
                const SizedBox(height: 10),
                Row(
                  children: [
                    FilledButton(
                      onPressed: () => ws.sendCommand('yes'),
                      child: const Text('Approve'),
                    ),
                    const SizedBox(width: 10),
                    OutlinedButton(
                      onPressed: () => ws.sendCommand('no'),
                      child: const Text('Reject'),
                    ),
                  ],
                ),
              ],
            ),
          ),
        const SizedBox(height: 14),
        _sectionTitle(
          'Orchestrator Approvals',
          count: '${orchApprovals.length}',
        ),
        const SizedBox(height: 8),
        if (orchApprovals.isEmpty)
          const Text('None', style: TextStyle(color: AppColors.textMuted)),
        for (final a in orchApprovals) _orchApprovalRow(ws, a),
        const SizedBox(height: 14),
        _sectionTitle('Code Approvals', count: '${codeApprovals.length}'),
        const SizedBox(height: 8),
        if (codeApprovals.isEmpty)
          const Text('None', style: TextStyle(color: AppColors.textMuted)),
        for (final a in codeApprovals) _codeApprovalRow(ws, a),
      ],
    );
  }

  Widget _orchApprovalRow(WebSocketService ws, Map<String, dynamic> a) {
    final stepId = a['step_id']?.toString() ?? '';
    final reason = a['reason']?.toString() ?? '';
    final createdAt = a['created_at']?.toString() ?? '';
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppColors.surfaceStrong.withValues(alpha: 0.58),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.border.withValues(alpha: 0.72)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            reason,
            style: const TextStyle(fontSize: 11, color: AppColors.textPrimary),
            maxLines: 3,
            overflow: TextOverflow.ellipsis,
          ),
          const SizedBox(height: 6),
          Text(
            createdAt,
            style: const TextStyle(fontSize: 10, color: AppColors.textMuted),
          ),
          const SizedBox(height: 10),
          Row(
            children: [
              FilledButton(
                onPressed: () => ws.approveOrchestratorStep(stepId, true),
                child: const Text('Approve'),
              ),
              const SizedBox(width: 10),
              OutlinedButton(
                onPressed: () => ws.approveOrchestratorStep(stepId, false),
                child: const Text('Reject'),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _codeApprovalRow(WebSocketService ws, Map<String, dynamic> a) {
    final requestId = a['request_id']?.toString() ?? '';
    final file = a['file']?.toString() ?? 'Unknown file';
    final diff = a['diff']?.toString() ?? '';
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppColors.surfaceStrong.withValues(alpha: 0.58),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.border.withValues(alpha: 0.72)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            file,
            style: const TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w800,
              color: AppColors.textPrimary,
            ),
          ),
          const SizedBox(height: 8),
          Container(
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: AppColors.surfaceElevated.withValues(alpha: 0.9),
              borderRadius: BorderRadius.circular(12),
              border: Border.all(
                color: AppColors.border.withValues(alpha: 0.62),
              ),
            ),
            child: Text(
              diff,
              maxLines: 6,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                fontFamily: 'monospace',
                fontSize: 10,
                color: AppColors.textMuted,
              ),
            ),
          ),
          const SizedBox(height: 10),
          Row(
            children: [
              FilledButton(
                onPressed: () => ws.sendCodeApprovalResponse(requestId, true),
                child: const Text('Approve'),
              ),
              const SizedBox(width: 10),
              OutlinedButton(
                onPressed: () => ws.sendCodeApprovalResponse(requestId, false),
                child: const Text('Reject'),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _scheduleTab(BuildContext context, WebSocketService ws) {
    final cron = ws.cronJobs;
    final projects = ws.orchestratorProjects;
    final tasks = ws.scheduledTasks;

    return ListView(
      padding: const EdgeInsets.all(12),
      children: [
        _tabHint(
          'Recurring jobs and night projects run automatically. Keep schedules tight and observable.',
        ),
        _sectionTitle('Cron Jobs', count: '${cron.length}'),
        const SizedBox(height: 8),
        if (cron.isEmpty)
          const Text('None', style: TextStyle(color: AppColors.textMuted)),
        for (final j in cron) _cronRow(context, ws, j),
        const SizedBox(height: 14),
        _sectionTitle('Scheduled Tasks', count: '${tasks.length}'),
        const SizedBox(height: 8),
        if (tasks.isEmpty)
          const Text('None', style: TextStyle(color: AppColors.textMuted)),
        for (final t in tasks) _scheduledTaskRow(t),
        const SizedBox(height: 14),
        _sectionTitle('Night Projects', count: '${projects.length}'),
        const SizedBox(height: 8),
        if (projects.isEmpty)
          const Text('None', style: TextStyle(color: AppColors.textMuted)),
        for (final p in projects) _projectRow(ws, p),
      ],
    );
  }

  Widget _cronRow(
    BuildContext context,
    WebSocketService ws,
    Map<String, dynamic> j,
  ) {
    final id = j['id']?.toString() ?? '';
    final name = j['name']?.toString() ?? id;
    final schedule = j['schedule']?.toString() ?? '';
    final enabled = j['enabled'] == true;
    final nextRun = j['next_run']?.toString() ?? '';

    return InkWell(
      onTap: () => _editCronDialog(context, ws, j),
      borderRadius: BorderRadius.circular(14),
      child: Container(
        margin: const EdgeInsets.only(bottom: 10),
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: AppColors.surfaceStrong.withValues(alpha: 0.58),
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: AppColors.border.withValues(alpha: 0.72)),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    name,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.w800,
                      color: AppColors.textPrimary,
                    ),
                  ),
                ),
                Switch(
                  value: enabled,
                  onChanged: (v) => ws.updateCronJob(id, enabled: v),
                ),
              ],
            ),
            const SizedBox(height: 6),
            Text(
              schedule,
              style: const TextStyle(fontSize: 11, color: AppColors.textMuted),
            ),
            const SizedBox(height: 6),
            Text(
              'next: $nextRun',
              style: const TextStyle(fontSize: 10, color: AppColors.textMuted),
            ),
          ],
        ),
      ),
    );
  }

  Widget _projectRow(WebSocketService ws, Map<String, dynamic> p) {
    final id = p['id']?.toString() ?? '';
    final name = p['name']?.toString() ?? id;
    final status = p['status']?.toString() ?? '';
    final start = p['run_start_hour']?.toString() ?? '';
    final end = p['run_end_hour']?.toString() ?? '';

    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppColors.surfaceStrong.withValues(alpha: 0.58),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.border.withValues(alpha: 0.72)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  name,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w800,
                    color: AppColors.textPrimary,
                  ),
                ),
              ),
              _pill(status, _statusColor(status)),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            'window: $start -> $end',
            style: const TextStyle(fontSize: 11, color: AppColors.textMuted),
          ),
          const SizedBox(height: 10),
          Row(
            children: [
              if (status == 'active')
                FilledButton(
                  onPressed: () => ws.pauseOrchestratorProject(id),
                  child: const Text('Pause'),
                )
              else if (status == 'paused')
                FilledButton(
                  onPressed: () => ws.resumeOrchestratorProject(id),
                  child: const Text('Resume'),
                )
              else
                const SizedBox.shrink(),
              const SizedBox(width: 10),
              OutlinedButton(
                onPressed: () => ws.cancelOrchestratorProject(id),
                child: const Text('Cancel'),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _memoryTab(WebSocketService ws) {
    final results = ws.memoryResults;
    return ListView(
      padding: const EdgeInsets.all(12),
      children: [
        _tabHint(
          'Search long-term memory to reuse prior decisions, constraints, and facts.',
        ),
        _sectionTitle('Search Memory', count: '${results.length}'),
        const SizedBox(height: 8),
        Row(
          children: [
            Expanded(
              child: TextField(
                controller: _memoryController,
                decoration: const InputDecoration(hintText: 'Search...'),
                onSubmitted: (_) => ws.memorySearch(_memoryController.text),
              ),
            ),
            const SizedBox(width: 10),
            FilledButton(
              onPressed: () => ws.memorySearch(_memoryController.text),
              child: const Text('Go'),
            ),
          ],
        ),
        const SizedBox(height: 10),
        if (results.isEmpty)
          const Text(
            'No results.',
            style: TextStyle(color: AppColors.textMuted),
          ),
        for (final r in results) _memoryRow(r),
      ],
    );
  }

  Widget _memoryRow(Map<String, dynamic> r) {
    final content = r['content']?.toString() ?? '';
    final score = r['score']?.toString() ?? '';
    final created = r['created_at']?.toString() ?? '';
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppColors.surfaceStrong.withValues(alpha: 0.58),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.border.withValues(alpha: 0.72)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            content,
            maxLines: 4,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(color: AppColors.textPrimary, fontSize: 11),
          ),
          const SizedBox(height: 6),
          Text(
            'score: $score | $created',
            style: const TextStyle(color: AppColors.textMuted, fontSize: 10),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
          ),
        ],
      ),
    );
  }

  Widget _evidenceTab(WebSocketService ws, List<Map<String, dynamic>> runs) {
    final selected = _selectedRunId.trim();
    final receipt = selected.isEmpty ? null : ws.runReceiptFor(selected);
    final receiptText = receipt?['receipt']?.toString() ?? '';
    final evidence = selected.isEmpty
        ? const []
        : _evidenceForRun(ws, selected);

    return ListView(
      padding: const EdgeInsets.all(12),
      children: [
        _tabHint(
          'Use receipts + evidence to validate completion quality before trusting autonomous outcomes.',
        ),
        _sectionTitle('Selected Run'),
        const SizedBox(height: 8),
        DropdownButtonFormField<String>(
          initialValue: selected.isEmpty ? null : selected,
          decoration: const InputDecoration(hintText: 'Select a run'),
          items: runs
              .map(
                (r) => DropdownMenuItem<String>(
                  value: r['id']?.toString() ?? '',
                  child: Text(
                    (r['user_text']?.toString() ?? '')
                        .replaceAll('\n', ' ')
                        .trim(),
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
              )
              .toList(),
          onChanged: (v) {
            final id = (v ?? '').trim();
            if (id.isEmpty) return;
            setState(() => _selectedRunId = id);
            ws.requestRunReceipt(id);
          },
        ),
        const SizedBox(height: 10),
        if (selected.isNotEmpty)
          Row(
            children: [
              Expanded(
                child: Text(
                  selected,
                  style: const TextStyle(
                    fontSize: 11,
                    color: AppColors.textMuted,
                  ),
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              IconButton(
                onPressed: () =>
                    Clipboard.setData(ClipboardData(text: selected)),
                icon: const Icon(Icons.copy, size: 18),
                tooltip: 'Copy run_id',
                color: AppColors.textMuted,
              ),
              FilledButton(
                onPressed: () => ws.requestRunReceipt(selected),
                child: const Text('Load Receipt'),
              ),
            ],
          ),
        const SizedBox(height: 12),
        _sectionTitle('Receipt'),
        const SizedBox(height: 8),
        Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: AppColors.surfaceElevated.withValues(alpha: 0.9),
            borderRadius: BorderRadius.circular(14),
            border: Border.all(color: AppColors.border.withValues(alpha: 0.62)),
          ),
          child: SelectableText(
            receiptText.isEmpty ? 'No receipt loaded.' : receiptText,
            style: const TextStyle(
              fontFamily: 'monospace',
              fontSize: 10,
              height: 1.35,
              color: AppColors.textPrimary,
            ),
          ),
        ),
        const SizedBox(height: 14),
        _sectionTitle('Evidence', count: '${evidence.length}'),
        const SizedBox(height: 8),
        if (evidence.isEmpty)
          const Text(
            'No evidence.',
            style: TextStyle(color: AppColors.textMuted),
          ),
        for (final e in evidence) _evidenceRow(e),
      ],
    );
  }

  Widget _evidenceRow(Map<String, dynamic> e) {
    final kind = e['kind']?.toString() ?? '';
    final value = e['value']?.toString() ?? '';
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppColors.surfaceStrong.withValues(alpha: 0.58),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.border.withValues(alpha: 0.72)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _pill(kind, AppColors.accent),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              value,
              maxLines: 3,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                fontSize: 11,
                color: AppColors.textPrimary,
              ),
            ),
          ),
          IconButton(
            onPressed: () => Clipboard.setData(ClipboardData(text: value)),
            icon: const Icon(Icons.copy, size: 18),
            tooltip: 'Copy',
            color: AppColors.textMuted,
          ),
        ],
      ),
    );
  }

  Widget _scheduledTaskRow(Map<String, dynamic> task) {
    final name = task['name']?.toString() ?? '(unnamed)';
    final scheduleType = task['schedule_type']?.toString() ?? '';
    final scheduleTime = task['schedule_time']?.toString() ?? '';
    final scheduleDay = task['schedule_day']?.toString() ?? '';
    final nextRun = task['next_run']?.toString() ?? '';
    final enabled = task['enabled'] == true;
    final statusText = enabled ? 'enabled' : 'disabled';
    final color = enabled ? AppColors.accentSoft : AppColors.textMuted;

    String schedule = '';
    if (scheduleType.isNotEmpty) {
      schedule = scheduleType;
    }
    if (scheduleTime.isNotEmpty) {
      schedule = schedule.isEmpty ? scheduleTime : '$schedule @ $scheduleTime';
    }
    if (scheduleDay.isNotEmpty) {
      schedule = '$schedule ($scheduleDay)';
    }

    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppColors.surfaceStrong.withValues(alpha: 0.58),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.border.withValues(alpha: 0.72)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  name,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w800,
                    color: AppColors.textPrimary,
                  ),
                ),
              ),
              _pill(statusText, color),
            ],
          ),
          const SizedBox(height: 6),
          if (schedule.isNotEmpty)
            Text(
              schedule,
              style: const TextStyle(fontSize: 11, color: AppColors.textMuted),
            ),
          if (nextRun.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text(
              'next: $nextRun',
              style: const TextStyle(fontSize: 10, color: AppColors.textMuted),
            ),
          ],
        ],
      ),
    );
  }

  List<Map<String, dynamic>> _evidenceForRun(
    WebSocketService ws,
    String runId,
  ) {
    final id = runId.trim();
    if (id.isEmpty) return const [];

    final seen = <String>{};
    final out = <Map<String, dynamic>>[];

    void addEvidence(String kind, String value, {String summary = ''}) {
      final k = kind.trim();
      final v = value.trim();
      if (k.isEmpty || v.isEmpty) return;
      final key = '$k|$v|$summary';
      if (seen.contains(key)) return;
      seen.add(key);
      out.add(<String, dynamic>{'kind': k, 'value': v, 'summary': summary});
    }

    // Primary: parse receipt.md if we have it.
    final receipt = ws.runReceiptFor(id);
    final receiptText = receipt?['receipt']?.toString() ?? '';
    if (receiptText.trim().isNotEmpty) {
      final lines = receiptText.split('\n');
      bool inEvidence = false;
      for (final raw in lines) {
        final line = raw.replaceAll('\r', '');
        final trimmed = line.trimRight();

        if (trimmed.trim() == '- evidence:') {
          inEvidence = true;
          continue;
        }
        if (trimmed.startsWith('- ') && trimmed.trim() != '- evidence:') {
          inEvidence = false;
        }
        if (!inEvidence) continue;
        if (!trimmed.startsWith('  - ')) continue;

        final body = trimmed.substring(4);
        final idx = body.indexOf(':');
        if (idx <= 0) continue;
        final kind = body.substring(0, idx).trim();
        final rest = body.substring(idx + 1).trim();
        if (kind.isEmpty || rest.isEmpty) continue;

        // Receipt format: "<value> <summary>" where summary is short and optional.
        const summaries = ['artifact', 'url', 'coords', 'app'];
        String value = rest;
        String summary = '';
        for (final s in summaries) {
          final suffix = ' $s';
          if (rest.endsWith(suffix)) {
            value = rest.substring(0, rest.length - suffix.length).trimRight();
            summary = s;
            break;
          }
        }
        addEvidence(kind, value, summary: summary);
      }
      return out;
    }

    // Fallback: scan run timeline events.
    for (final evt in ws.runTimeline) {
      try {
        final run = evt['run'];
        if (run is! Map) continue;
        final rid = run['id']?.toString() ?? '';
        if (rid != id) continue;
        final step = evt['step'];
        if (step is! Map) continue;
        final evidence = step['evidence'];
        if (evidence is! List) continue;
        for (final item in evidence) {
          if (item is! Map) continue;
          final kind = item['kind']?.toString() ?? '';
          final value = item['value']?.toString() ?? '';
          final summary = item['summary']?.toString() ?? '';
          addEvidence(kind, value, summary: summary);
        }
      } catch (_) {
        continue;
      }
    }

    return out;
  }

  Future<void> _editCronDialog(
    BuildContext context,
    WebSocketService ws,
    Map<String, dynamic> job,
  ) async {
    final id = job['id']?.toString() ?? '';
    if (id.trim().isEmpty) return;

    final nameController = TextEditingController(
      text: job['name']?.toString() ?? '',
    );
    final scheduleController = TextEditingController(
      text: job['schedule']?.toString() ?? '',
    );

    final result = await showDialog<String>(
      context: context,
      builder: (context) {
        return AlertDialog(
          title: const Text('Edit Cron Job'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: nameController,
                decoration: const InputDecoration(labelText: 'Name'),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: scheduleController,
                decoration: const InputDecoration(labelText: 'Schedule'),
              ),
              const SizedBox(height: 10),
              Text(
                'Tip: use cron like "0 9 * * *" or interval like "every 30m".',
                style: const TextStyle(
                  fontSize: 11,
                  color: AppColors.textMuted,
                ),
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(context).pop('cancel'),
              child: const Text('Cancel'),
            ),
            OutlinedButton(
              onPressed: () {
                ws.cancelCronJob(id);
                Navigator.of(context).pop('delete');
              },
              child: const Text('Delete'),
            ),
            FilledButton(
              onPressed: () => Navigator.of(context).pop('save'),
              child: const Text('Save'),
            ),
          ],
        );
      },
    );

    if (result != 'save') return;

    final name = nameController.text.trim();
    final schedule = scheduleController.text.trim();
    ws.updateCronJob(
      id,
      name: name.isEmpty ? null : name,
      schedule: schedule.isEmpty ? null : schedule,
    );
  }
}
