import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:crypto/crypto.dart';
import 'package:web_socket_channel/io.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:window_manager/window_manager.dart';

import '../models/a2ui.dart';

class WebSocketService extends ChangeNotifier {
  WebSocketChannel? _channel;
  bool _isConnected = false;
  String _status = 'idle';
  double _audioLevel = 0.0;
  String _transcript = '';
  String _gesture = '';
  List<Map<String, dynamic>> _capabilities = [];
  final List<Map<String, dynamic>> _messages = [];
  Timer? _reconnectTimer;
  List<Map<String, String>> _activityLog = [];
  final List<Map<String, dynamic>> _backendLogs = [];
  List<Map<String, dynamic>> _scheduledTasks = [];
  List<Map<String, dynamic>> _sessions = [];
  List<Map<String, dynamic>> _cronJobs = [];
  List<Map<String, dynamic>> _changeLog = [];
  final Map<String, List<Map<String, dynamic>>> _sessionHistory = {};
  final Map<String, Completer<List<Map<String, dynamic>>>>
  _sessionHistoryWaiters = {};
  Map<String, dynamic> _usage = {};
  List<Map<String, dynamic>> _jobApplications = [];
  String _lastCapability = '';
  String _lastModel = '';
  String _traceId = '';
  String _speakingText = '';
  final List<bool> _wakeWordSamples = List<bool>.filled(5, false);
  final int _wakeWordSampleCount = 5;
  String _wakeWordTrainingStatus = '';
  String _wakeWordTrainingMessage = '';
  int? _wakeWordRecordingIndex;

  // Orchestrator (night projects) dashboard state
  List<Map<String, dynamic>> _orchestratorProjects = [];
  final Map<String, List<Map<String, dynamic>>> _orchestratorStepsByProject =
      {};
  final Map<String, List<String>> _orchestratorMissingInputs = {};
  List<Map<String, dynamic>> _orchestratorApprovals = [];

  // Pending code approvals (in addition to dialog stream)
  final List<Map<String, dynamic>> _pendingCodeApprovals = [];

  // Gateway specific
  String _gatewayHost = '127.0.0.1';
  int _gatewayPort = 8765;
  bool _usingAutoPort = true;
  String? _sessionId;

  // Runs (interactive task timeline)
  Map<String, dynamic> _runsSnapshot = {};
  final List<Map<String, dynamic>> _runTimeline = [];

  // Memory + evidence helpers
  String _memoryLastQuery = '';
  List<Map<String, dynamic>> _memoryResults = [];
  final Map<String, Map<String, dynamic>> _runReceipts = {};

  // Integrations snapshot (Calendar, Email, Providers)
  Map<String, dynamic> _integrations = {};
  Map<String, dynamic> _integrationsLastResult = {};

  final List<A2UIView> _a2uiViews = [];
  Map<String, dynamic> _hud = {};
  Map<String, dynamic> _canvasState = {};

  // Code Approval Stream
  final _approvalRequestController =
      StreamController<Map<String, dynamic>>.broadcast();
  Stream<Map<String, dynamic>> get approvalRequests =>
      _approvalRequestController.stream;

  WebSocketService({bool autoConnect = true}) {
    if (autoConnect) {
      connect();
    }
  }

  // Getters
  bool get isConnected => _isConnected;
  String get status => _status;
  String get assistantState => _status;
  double get audioLevel => _audioLevel;
  String get transcript => _transcript;
  String get gesture => _gesture;
  List<Map<String, dynamic>> get capabilities => _capabilities;
  List<Map<String, dynamic>> get messages => _messages;
  List<bool> get wakeWordSamples => _wakeWordSamples;
  int get wakeWordSampleCount => _wakeWordSampleCount;
  int? get wakeWordRecordingIndex => _wakeWordRecordingIndex;
  String get wakeWordTrainingStatus => _wakeWordTrainingStatus;
  String get wakeWordTrainingMessage => _wakeWordTrainingMessage;
  bool get usingAutoPort => _usingAutoPort;
  String get resolvedHost => _gatewayHost;
  int get resolvedPort => _gatewayPort;
  List<A2UIView> get a2uiViews => List.unmodifiable(_a2uiViews);
  List<Map<String, String>> get activityLog => _activityLog;
  List<Map<String, dynamic>> get backendLogs => List.unmodifiable(_backendLogs);
  List<Map<String, dynamic>> get scheduledTasks => _scheduledTasks;
  List<Map<String, dynamic>> get sessions => _sessions;
  List<Map<String, dynamic>> get cronJobs => _cronJobs;
  List<Map<String, dynamic>> get changeLog => _changeLog;
  Map<String, dynamic> get usage => _usage;
  List<Map<String, dynamic>> get jobApplications => _jobApplications;
  List<Map<String, dynamic>>? getSessionHistory(String sessionId) =>
      _sessionHistory[sessionId];
  Map<String, dynamic> get hud => _hud;
  Map<String, dynamic> get canvasState => _canvasState;
  String get lastCapability => _lastCapability;
  String get lastModel => _lastModel;
  String get traceId => _traceId;
  String get speakingText => _speakingText;
  String? get sessionId => _sessionId;
  List<Map<String, dynamic>> get orchestratorProjects => _orchestratorProjects;
  List<Map<String, dynamic>> get orchestratorApprovals =>
      _orchestratorApprovals;
  Map<String, List<Map<String, dynamic>>> get orchestratorStepsByProject =>
      _orchestratorStepsByProject;
  List<Map<String, dynamic>> get pendingCodeApprovals =>
      List.unmodifiable(_pendingCodeApprovals);
  List<String> missingInputsForProject(String projectId) =>
      _orchestratorMissingInputs[projectId] ?? const [];
  Map<String, dynamic> get runsSnapshot => _runsSnapshot;
  List<Map<String, dynamic>> get runTimeline => List.unmodifiable(_runTimeline);
  String get memoryLastQuery => _memoryLastQuery;
  List<Map<String, dynamic>> get memoryResults => List.unmodifiable(_memoryResults);
  Map<String, dynamic>? runReceiptFor(String runId) => _runReceipts[runId];
  Map<String, dynamic> get integrations => _integrations;
  Map<String, dynamic> get integrationsLastResult => _integrationsLastResult;

  Future<void> connect({String host = '127.0.0.1', int? port}) async {
    _gatewayHost = host;
    _usingAutoPort = port == null;
    if (_usingAutoPort) {
      await _loadAutoPortFromFile();
    } else if (port != null) {
      _gatewayPort = port;
    }
    await _tryConnect();
  }

  String? _userHomeDir() {
    // Cross-platform "home" discovery (best-effort).
    final env = Platform.environment;
    final win = env['USERPROFILE'];
    if (win != null && win.trim().isNotEmpty) return win.trim();
    final nix = env['HOME'];
    if (nix != null && nix.trim().isNotEmpty) return nix.trim();
    return null;
  }

  Future<void> _loadAutoPortFromFile() async {
    try {
      final home = _userHomeDir();
      if (home == null) return;
      final f = File('$home/.chintu/ws_port.json');
      if (!await f.exists()) return;
      final raw = await f.readAsString();
      final parsed = jsonDecode(raw);
      if (parsed is! Map) return;
      final port = parsed['port'];
      final host = parsed['host'];
      if (host is String && host.trim().isNotEmpty) {
        _gatewayHost = host.trim();
      }
      if (port is int && port > 0 && port < 65536) {
        _gatewayPort = port;
      } else if (port is String) {
        final p = int.tryParse(port.trim());
        if (p != null && p > 0 && p < 65536) _gatewayPort = p;
      }
    } catch (_) {
      // Ignore and keep defaults.
    }
  }

  Future<String?> _loadGatewaySecret() async {
    try {
      final env = Platform.environment['CHINTU_GATEWAY_SECRET'];
      if (env != null && env.trim().isNotEmpty) return env.trim();
      final home = _userHomeDir();
      if (home == null) return null;
      final f = File('$home/.chintu/gateway_secret');
      if (!await f.exists()) return null;
      final raw = await f.readAsString();
      final secret = raw.trim();
      return secret.isNotEmpty ? secret : null;
    } catch (_) {
      return null;
    }
  }

  String _hmacSha256Hex(String secret, String message) {
    final hmacSha256 = Hmac(sha256, utf8.encode(secret));
    return hmacSha256.convert(utf8.encode(message)).toString();
  }

  Future<void> _sendConnectAuth({
    required String sessionId,
    required String challenge,
    required bool authRequired,
  }) async {
    if (_channel == null) return;
    String response = '';
    if (authRequired) {
      final secret = await _loadGatewaySecret();
      if (secret != null && secret.isNotEmpty && challenge.isNotEmpty) {
        response = _hmacSha256Hex(secret, challenge);
      }
    }
    final authFrame = {
      'type': 'connect.auth',
      'session_id': sessionId,
      'response': response,
      'role': 'primary',
      'capabilities': ['display', 'audio_out', 'input'],
      'metadata': {'platform': Platform.operatingSystem, 'client': 'flutter'},
    };
    _channel!.sink.add(jsonEncode(authFrame));
  }

  Future<void> _tryConnect() async {
    try {
      debugPrint(
        'Connecting to Gateway at ws://$_gatewayHost:$_gatewayPort...',
      );
      final socket = await WebSocket.connect(
        'ws://$_gatewayHost:$_gatewayPort',
      );
      _channel = IOWebSocketChannel(socket);
      _channel!.stream.listen(
        _onMessage,
        onError: (error) {
          debugPrint('WS Error: $error');
          _handleDisconnect();
        },
        onDone: () => _handleDisconnect(),
      );

      // === GATEWAY HANDSHAKE ===
      // 1. Send Connect Frame
      _sendGatewayConnect();

      // Note: _isConnected becomes true only after READY frame
    } catch (e) {
      debugPrint('Connection failed: $e');
      _isConnected = false;
      notifyListeners();
      _scheduleReconnect();
    }
  }

  void _sendGatewayConnect() {
    if (_channel == null) return;

    final connectFrame = {
      'type': 'connect',
      'role': 'primary',
      'protocol_version': '1.0',
      'device_id': 'flutter_ui_${DateTime.now().millisecondsSinceEpoch}',
      'capabilities': ['display', 'audio_out', 'input'],
      'metadata': {
        'platform': Platform.operatingSystem,
        'client': 'flutter',
        'client_role': 'ui',
      },
    };

    _channel!.sink.add(jsonEncode(connectFrame));
  }

  void _handleDisconnect() {
    debugPrint('Disconnected from Gateway');
    _isConnected = false;
    _sessionId = null;
    notifyListeners();
    _scheduleReconnect();
  }

  void _scheduleReconnect() {
    _reconnectTimer?.cancel();
    _reconnectTimer = Timer(const Duration(seconds: 2), () => _tryConnect());
  }

  @override
  void dispose() {
    _approvalRequestController.close();
    _reconnectTimer?.cancel();
    _channel?.sink.close();
    super.dispose();
  }

  void _onMessage(dynamic data) {
    try {
      final envelope = jsonDecode(data as String) as Map<String, dynamic>;
      final type = envelope['type'] as String?;

      switch (type) {
        // --- HANDSHAKE FRAMES ---
        case 'welcome':
          debugPrint('Gateway Welcome received');
          // No auth for now, wait for ready
          break;

        case 'connect.challenge':
          try {
            final sessionId = envelope['session_id']?.toString() ?? '';
            final challenge = envelope['challenge']?.toString() ?? '';
            final authRequired = envelope['auth_required'] == true;
            // If the backend does auto-auth (auth_required=false), don't respond here.
            if (authRequired && sessionId.isNotEmpty) {
              _sendConnectAuth(
                sessionId: sessionId,
                challenge: challenge,
                authRequired: authRequired,
              );
            }
          } catch (_) {}
          break;

        case 'connect.ready':
          debugPrint('Gateway Ready received (connect.ready)');
          _isConnected = true;
          _sessionId = envelope['session_id']?.toString();
          _sendGatewayEvent('ui_ready', {'session_id': _sessionId ?? ''});
          notifyListeners();
          break;

        case 'ready':
          debugPrint('Gateway Ready received');
          _isConnected = true;
          _sessionId = envelope['session_id'];
          _sendGatewayEvent('ui_ready', {'session_id': _sessionId ?? ''});
          notifyListeners();
          break;

        case 'error':
          _handleError(envelope);
          break;
        case 'code_approval_request':
          // Keep a lightweight list for dashboards, in addition to the dialog stream.
          final reqId = envelope['request_id']?.toString() ?? '';
          if (reqId.isNotEmpty) {
            _pendingCodeApprovals.removeWhere(
              (r) => r['request_id']?.toString() == reqId,
            );
          }
          _pendingCodeApprovals.add(envelope);
          _approvalRequestController.add(envelope);
          notifyListeners();
          break;

        // --- DATA FRAMES ---
        case 'event':
        case 'command': // If UI receives commands to execute
          final payload = envelope['payload'] as Map<String, dynamic>?;
          if (payload != null) {
            _dispatchPayload(payload);
          }
          break;

        default:
          // Legacy fallback or direct message type
          _dispatchPayload(envelope);
      }
    } catch (e) {
      debugPrint('Error parsing message: $e');
    }
  }

  void _dispatchPayload(Map<String, dynamic> payload) {
    // Wrapper style: { event: "...", data: {...} }
    final event = payload['event'] as String?;
    if (event != null) {
      final rawData = payload['data'];
      final data = rawData is Map
          ? Map<String, dynamic>.from(rawData)
          : <String, dynamic>{};
      _dispatchEvent(event, data);
      return;
    }

    // Direct style: { type: "...", data: ... }
    final type = payload['type'] as String?;
    if (type == null) return;

    if (type == 'session_history') {
      final sessionId = payload['session_id'] as String? ?? '';
      final list = payload['data'] as List? ?? [];
      final history = list.map((e) => Map<String, dynamic>.from(e)).toList();
      _sessionHistory[sessionId] = history;
      final waiter = _sessionHistoryWaiters.remove(sessionId);
      if (waiter != null && !waiter.isCompleted) {
        waiter.complete(history);
      }
      notifyListeners();
      return;
    }

    final rawData = payload['data'];
    final data = rawData is Map
        ? Map<String, dynamic>.from(rawData)
        : <String, dynamic>{};
    _dispatchEvent(type, data);
  }

  void _dispatchEvent(String type, Map<String, dynamic> data) {
    switch (type) {
      case 'state_update':
        _handleStateUpdate(data);
        break;
      case 'transcript':
        _handleTranscript(data);
        break;
      case 'response':
        _handleResponse(data);
        break;
      case 'canvas_update':
        _handleCanvasUpdate(data);
        break;
      case 'audio_level':
        _audioLevel = (data['level'] as num?)?.toDouble() ?? 0.0;
        notifyListeners();
        break;
      case 'run_snapshot':
        _handleRunSnapshot(data);
        break;
      case 'run_update':
        _handleRunUpdate(data);
        break;
      case 'memory_search_result':
        _handleMemorySearchResult(data);
        break;
      case 'run_receipt':
        _handleRunReceipt(data);
        break;
      case 'integrations_snapshot':
        _handleIntegrationsSnapshot(data);
        break;
      case 'integrations_action_result':
        _handleIntegrationsActionResult(data);
        break;
      default:
        _handleLegacyTypes(type, data);
    }
  }

  void _handleIntegrationsSnapshot(Map<String, dynamic> data) {
    final raw = data['integrations'];
    if (raw is Map) {
      _integrations = Map<String, dynamic>.from(raw);
    }
    notifyListeners();
  }

  void _handleIntegrationsActionResult(Map<String, dynamic> data) {
    _integrationsLastResult = Map<String, dynamic>.from(data);
    final raw = data['integrations'];
    if (raw is Map) {
      _integrations = Map<String, dynamic>.from(raw);
    }
    final message = data['message']?.toString() ?? '';
    if (message.isNotEmpty) {
      _addMessage('system', '[Integrations] $message');
    }
    notifyListeners();
  }

  void _handleMemorySearchResult(Map<String, dynamic> data) {
    _memoryLastQuery = data['query']?.toString() ?? _memoryLastQuery;
    final raw = data['results'];
    if (raw is List) {
      _memoryResults = raw.map((e) => Map<String, dynamic>.from(e)).toList();
    } else {
      _memoryResults = [];
    }
    notifyListeners();
  }

  void _handleRunReceipt(Map<String, dynamic> data) {
    final runId = data['run_id']?.toString() ?? '';
    if (runId.isEmpty) return;
    _runReceipts[runId] = Map<String, dynamic>.from(data);
    notifyListeners();
  }

  void _handleLegacyTypes(String type, Map<String, dynamic> data) {
    switch (type) {
      case 'status':
        _status = data['status'] as String? ?? 'idle';
        break;
      case 'gesture':
        _gesture = data['gesture'] as String? ?? '';
        break;
      case 'capabilities': // or capabilities_list
      case 'capabilities_list':
        // Align protocol here
        _capabilities = List<Map<String, dynamic>>.from(
          data['capabilities'] as List? ?? [],
        );
        break;
      case 'a2ui_render':
        _handleA2UIRender(data);
        break;
      case 'a2ui_update':
        _handleA2UIUpdate(data);
        break;
      case 'a2ui_clear':
        _handleA2UIClear(data);
        break;
      case 'a2ui_toast':
        _handleA2UIToast(data);
        break;
      case 'log_event':
        _handleLogEvent(data);
        break;
      case 'window_control':
        // Extract action from data
        _handleWindowControl(data['action'] as String? ?? '');
        break;
      case 'canvas_update':
        _handleCanvasUpdate(data);
        break;
      case 'session_history':
        final sessionId = data['session_id'] as String? ?? '';
        final payload = data['data'] as List? ?? [];
        final history = payload
            .map((e) => Map<String, dynamic>.from(e))
            .toList();
        _sessionHistory[sessionId] = history;
        final waiter = _sessionHistoryWaiters.remove(sessionId);
        if (waiter != null && !waiter.isCompleted) {
          waiter.complete(history);
        }
        break;
      case 'copy_to_clipboard':
        final status = data['status'] as String? ?? 'ok';
        if (status == 'error') {
          final error = data['error'] as String? ?? 'Clipboard error';
          _addMessage('system', '[Clipboard] $error');
        } else {
          _addMessage('system', 'Path copied to clipboard');
        }
        break;
      case 'cron_update':
        final status = data['status'] as String? ?? 'ok';
        if (status == 'error') {
          final error = data['error'] as String? ?? 'Cron update failed';
          _addMessage('system', '[Cron] $error');
        }
        break;
      case 'cron_cancel':
        final status = data['status'] as String? ?? 'ok';
        if (status == 'error') {
          final error = data['error'] as String? ?? 'Cron cancel failed';
          _addMessage('system', '[Cron] $error');
        }
        break;
      case 'orchestrator_snapshot':
        _applyOrchestratorSnapshot(data);
        break;
      case 'orchestrator_update':
        _applyOrchestratorUpdate(data);
        break;
      case 'orchestrator_request':
        _applyOrchestratorRequest(data);
        break;
    }
    notifyListeners();
  }

  void _handleTranscript(Map<String, dynamic> data) {
    final text = data['text'] as String?;
    if (text != null) {
      _transcript = text;
      if (text.isNotEmpty && data['is_final'] == true) {
        _addMessage('user', text);
      }
      notifyListeners();
    }
  }

  void _handleResponse(Map<String, dynamic> data) {
    final text = data['text'] as String?;
    if (text != null && text.isNotEmpty) {
      final isDuplicate = _messages.any(
        (msg) => msg['role'] == 'assistant' && msg['content'] == text,
      );
      if (!isDuplicate) {
        _addMessage('assistant', text);
      }
      notifyListeners();
    }
  }

  void _handleCanvasUpdate(Map<String, dynamic> data) {
    final canvas = data['canvas'];
    if (canvas is Map) {
      _canvasState = Map<String, dynamic>.from(canvas);
    } else if (data.isNotEmpty) {
      _canvasState = Map<String, dynamic>.from(data);
    }
    notifyListeners();
  }

  // --- Sending to Backend via Gateway ---
  // We wrap outgoing actions in an 'event' frame targeted at 'core'

  void _sendGatewayEvent(String eventName, Map<String, dynamic> data) {
    if (!_isConnected || _channel == null) return;

    final frame = {
      'type': 'event',
      'target': 'core', // Route to Core Node
      'payload': {
        'event': 'ui_action',
        'data': {'action': eventName, ...data},
      },
    };

    _channel!.sink.add(jsonEncode(frame));
  }

  void sendCommand(String command, {List<String>? attachments}) {
    if (command.isEmpty) return;
    final payload = <String, dynamic>{'text': command};
    if (attachments != null && attachments.isNotEmpty) {
      payload['attachments'] = attachments;
    }
    _sendGatewayEvent('text_input', payload);
    _addMessage('user', command);
    notifyListeners();
  }

  void cancelRun(String runId) {
    final id = runId.trim();
    if (id.isEmpty) return;
    _sendGatewayEvent('run_cancel', <String, dynamic>{'run_id': id});
  }

  void memorySearch(String query, {int limit = 8}) {
    final q = query.trim();
    if (q.isEmpty) return;
    final bounded = limit.clamp(1, 50);
    final requestId = DateTime.now().microsecondsSinceEpoch.toString();
    _sendGatewayEvent('memory_search', <String, dynamic>{
      'query': q,
      'limit': bounded,
      'request_id': requestId,
    });
  }

  void requestRunReceipt(String runId) {
    final id = runId.trim();
    if (id.isEmpty) return;
    final requestId = DateTime.now().microsecondsSinceEpoch.toString();
    _sendGatewayEvent('run_receipt_get', <String, dynamic>{
      'run_id': id,
      'request_id': requestId,
    });
  }

  void requestOrchestratorSnapshot() {
    _sendGatewayEvent(
      'orchestrator_snapshot_request',
      const <String, dynamic>{},
    );
  }

  void approveOrchestratorStep(String stepId, bool approve) {
    if (stepId.trim().isEmpty) return;
    _sendGatewayEvent('orchestrator_approve_step', <String, dynamic>{
      'step_id': stepId.trim(),
      'approve': approve,
    });
  }

  void setOrchestratorInput({
    required String projectId,
    required String key,
    required String value,
    bool isSecret = false,
  }) {
    if (key.trim().isEmpty) return;
    _sendGatewayEvent('orchestrator_set_input', <String, dynamic>{
      'project_id': projectId.trim(),
      'key': key.trim(),
      'value': value,
      'is_secret': isSecret,
    });
  }

  void pauseOrchestratorProject(String projectId) {
    if (projectId.trim().isEmpty) return;
    _sendGatewayEvent('orchestrator_pause_project', <String, dynamic>{
      'project_id': projectId.trim(),
    });
  }

  void resumeOrchestratorProject(String projectId) {
    if (projectId.trim().isEmpty) return;
    _sendGatewayEvent('orchestrator_resume_project', <String, dynamic>{
      'project_id': projectId.trim(),
    });
  }

  void cancelOrchestratorProject(String projectId) {
    if (projectId.trim().isEmpty) return;
    _sendGatewayEvent('orchestrator_cancel_project', <String, dynamic>{
      'project_id': projectId.trim(),
    });
  }

  // Wake word training (UI only; backend may ignore if unsupported)
  void requestWakeWordStatus() {
    _sendGatewayEvent('wake_word_status_request', const <String, dynamic>{});
  }

  void recordWakeWordSample(int index) {
    _wakeWordRecordingIndex = index;
    notifyListeners();
    _sendGatewayEvent('wake_word_record_sample', <String, dynamic>{
      'index': index,
      'kind': 'positive',
    });
  }

  void trainWakeWord() {
    _wakeWordTrainingStatus = 'requested';
    _wakeWordTrainingMessage = 'Training requested...';
    notifyListeners();
    _sendGatewayEvent('wake_word_train', const <String, dynamic>{});
  }

  void copyToClipboard(String text) {
    if (_channel == null) return;
    _channel!.sink.add(jsonEncode({'type': 'copy_to_clipboard', 'text': text}));
  }

  void updateCronJob(
    String jobId, {
    String? schedule,
    String? name,
    bool? enabled,
  }) {
    if (_channel == null || jobId.isEmpty) return;
    final payload = <String, dynamic>{'type': 'cron_update', 'job_id': jobId};
    if (schedule != null) payload['schedule'] = schedule;
    if (name != null) payload['name'] = name;
    if (enabled != null) payload['enabled'] = enabled;
    _channel!.sink.add(jsonEncode(payload));
  }

  void cancelCronJob(String jobId) {
    if (_channel == null || jobId.isEmpty) return;
    _channel!.sink.add(jsonEncode({'type': 'cron_cancel', 'job_id': jobId}));
  }

  Future<List<Map<String, dynamic>>> requestSessionHistory(
    String sessionId, {
    int limit = 50,
  }) async {
    if (_channel == null) return [];
    if (_sessionHistory.containsKey(sessionId)) {
      return _sessionHistory[sessionId] ?? [];
    }
    final completer = Completer<List<Map<String, dynamic>>>();
    _sessionHistoryWaiters[sessionId] = completer;
    _channel!.sink.add(
      jsonEncode({
        'type': 'session_history',
        'session_id': sessionId,
        'limit': limit,
      }),
    );
    return completer.future.timeout(
      const Duration(seconds: 3),
      onTimeout: () {
        _sessionHistoryWaiters.remove(sessionId);
        return _sessionHistory[sessionId] ?? [];
      },
    );
  }

  void sendCanvasAction(Map<String, dynamic> action) {
    if (action.isEmpty) return;
    _sendGatewayEvent('canvas_action', {'canvas': action});
  }

  Future<void> sendA2UIAction(
    String viewId,
    String actionId, {
    Map<String, dynamic>? payload,
    Map<String, dynamic>? form,
  }) async {
    _sendGatewayEvent('a2ui_action', {
      'view_id': viewId,
      'action_id': actionId,
      'payload': payload ?? const <String, dynamic>{},
      'form': form ?? const <String, dynamic>{},
    });
  }

  void sendCodeApprovalResponse(String requestId, bool approved) {
    if (_channel == null) return;
    _pendingCodeApprovals.removeWhere(
      (r) => r['request_id']?.toString() == requestId,
    );
    final frame = {
      'type': 'code_approval_response',
      'request_id': requestId,
      'approved': approved,
    };
    _channel!.sink.add(jsonEncode(frame));
    notifyListeners();
  }

  void startPushToTalk() {
    _sendGatewayEvent('push_to_talk', {'state': 'start'});
  }

  void stopPushToTalk() {
    _sendGatewayEvent('push_to_talk', {'state': 'stop'});
  }

  // --- Logic Preserved from Original File (State Parsing, A2UI, Windows) ---

  void _handleStateUpdate(Map<String, dynamic> data) {
    _status =
        (data['assistant_state'] as String?) ??
        (data['status'] as String?) ??
        _status;
    _audioLevel = (data['audio_level'] as num?)?.toDouble() ?? _audioLevel;

    _lastCapability = data['last_capability'] as String? ?? _lastCapability;
    _lastModel = data['last_model'] as String? ?? _lastModel;
    _traceId = data['trace_id'] as String? ?? _traceId;
    _speakingText = data['speaking_text'] as String? ?? _speakingText;

    // Legacy transcript field in state?
    final tr = data['transcript'] as String?;
    if (tr != null) _transcript = tr;

    final detectedHand = data['detected_hand'] as bool? ?? false;
    final gesture = data['current_gesture'] as String? ?? '';
    _gesture = detectedHand ? gesture : '';

    final features = data['features'] as Map<String, dynamic>?;
    if (features != null) {
      _capabilities = features.entries.map((entry) {
        final value = entry.value as Map<String, dynamic>? ?? {};
        final enabled = value['enabled'] ?? true;
        final status = value['status'] as String? ?? 'inactive';
        return {
          'id': entry.key,
          'name': value['name'] ?? entry.key,
          'enabled': enabled,
          'status': status,
          'active': enabled && status == 'active',
        };
      }).toList();
    }

    final logs = data['activity_log'] as List?;
    if (logs != null) {
      _activityLog = logs.map((e) => Map<String, String>.from(e)).toList();
    }

    final tasks = data['scheduled_tasks'] as List?;
    if (tasks != null) {
      _scheduledTasks = tasks.map((e) => Map<String, dynamic>.from(e)).toList();
    }

    final sessions = data['sessions'] as List?;
    if (sessions != null) {
      _sessions = sessions.map((e) => Map<String, dynamic>.from(e)).toList();
    }

    final cronJobs = data['cron_jobs'] as List?;
    if (cronJobs != null) {
      _cronJobs = cronJobs.map((e) => Map<String, dynamic>.from(e)).toList();
    }

    final changes = data['change_log'] as List?;
    if (changes != null) {
      _changeLog = changes.map((e) => Map<String, dynamic>.from(e)).toList();
    }

    final usage = data['usage'];
    if (usage is Map) {
      _usage = Map<String, dynamic>.from(usage);
    }

    final jobApps = data['job_applications'] as List?;
    if (jobApps != null) {
      _jobApplications = jobApps
          .map((e) => Map<String, dynamic>.from(e))
          .toList();
    }

    final hud = data['hud'];
    if (hud is Map) {
      _hud = Map<String, dynamic>.from(hud);
    }

    final canvas = data['canvas'];
    if (canvas is Map) {
      _canvasState = Map<String, dynamic>.from(canvas);
    }

    final integrations = data['integrations'];
    if (integrations is Map) {
      _integrations = Map<String, dynamic>.from(integrations);
    }

    notifyListeners();
  }

  // --- Integrations (UI helpers) ---
  void requestIntegrationsSnapshot() {
    final requestId = DateTime.now().microsecondsSinceEpoch.toString();
    _sendGatewayEvent('integrations_snapshot_request', <String, dynamic>{
      'request_id': requestId,
    });
  }

  void saveGoogleCalendarCredentials(String credentialsJson) {
    final json = credentialsJson.trim();
    if (json.isEmpty) return;
    _sendGatewayEvent('google_calendar_save_credentials', <String, dynamic>{
      'credentials_json': json,
    });
  }

  void authenticateGoogleCalendar() {
    _sendGatewayEvent('google_calendar_authenticate', const <String, dynamic>{});
  }

  void requestOAuthAction({
    required String provider,
    required String operation,
    bool writeAccess = false,
    bool forceReauth = false,
    bool removeCredentials = false,
    String? credentialsPath,
  }) {
    final p = provider.trim().toLowerCase();
    final op = operation.trim().toLowerCase();
    if (p.isEmpty || op.isEmpty) return;
    _sendGatewayEvent('oauth_action', <String, dynamic>{
      'provider': p,
      'operation': op,
      'write_access': writeAccess,
      'force_reauth': forceReauth,
      'remove_credentials': removeCredentials,
      if ((credentialsPath ?? '').trim().isNotEmpty)
        'credentials_path': (credentialsPath ?? '').trim(),
    });
  }

  void saveEmailImapConfig({
    required String host,
    required int port,
    required String user,
    required String folder,
    required String password,
  }) {
    _sendGatewayEvent('email_imap_save_config', <String, dynamic>{
      'host': host.trim(),
      'port': port,
      'user': user.trim(),
      'folder': folder.trim(),
      'password': password,
    });
  }

  void testEmailImapConnection() {
    _sendGatewayEvent('email_imap_test_connection', const <String, dynamic>{});
  }

  void saveProviderApiKey({required String provider, required String apiKey}) {
    final p = provider.trim().toLowerCase();
    final key = apiKey.trim();
    if (p.isEmpty || key.isEmpty) return;
    _sendGatewayEvent('provider_key_save', <String, dynamic>{
      'provider': p,
      'api_key': key,
    });
  }

  void _handleError(Map<String, dynamic> data) {
    // Gateway error envelope?
    final msg = data['message'] as String? ?? 'Unknown Error';
    _addMessage('system', '[ERROR] $msg');
    notifyListeners();
  }

  void _handleLogEvent(Map<String, dynamic> data) {
    _backendLogs.add(data);
    if (_backendLogs.length > 500) _backendLogs.removeAt(0);
    notifyListeners();
  }

  void _handleRunSnapshot(Map<String, dynamic> data) {
    _runsSnapshot = Map<String, dynamic>.from(data);
    notifyListeners();
  }

  void _handleRunUpdate(Map<String, dynamic> data) {
    final evt = Map<String, dynamic>.from(data);
    _runTimeline.add(evt);
    if (_runTimeline.length > 400) {
      _runTimeline.removeRange(0, _runTimeline.length - 400);
    }

    // Best-effort: keep snapshot in sync without requiring a full refresh.
    try {
        final run = evt['run'];
        final action = evt['action']?.toString() ?? '';
        if (run is Map) {
          final runMap = Map<String, dynamic>.from(run);
        final runId = runMap['id']?.toString() ?? '';
        final sessionId = runMap['session_id']?.toString() ?? '';

        if (runId.isNotEmpty) {
          final runs = _runsSnapshot['runs'];
          if (runs is List) {
            final idx = runs.indexWhere(
              (r) => (r is Map) && (r['id']?.toString() == runId),
            );
            if (idx >= 0) {
              runs[idx] = runMap;
            } else {
              runs.insert(0, runMap);
            }
          } else {
            _runsSnapshot['runs'] = [runMap];
          }
        }

        final queue = evt['queue'];
        if (sessionId.isNotEmpty && queue is Map) {
          final lanes = _runsSnapshot['lanes'];
          final laneMap = lanes is Map
              ? Map<String, dynamic>.from(lanes)
              : <String, dynamic>{};
          laneMap[sessionId] = Map<String, dynamic>.from(queue);
          _runsSnapshot['lanes'] = laneMap;
        }

        if (action == 'waiting_approval') {
          _runsSnapshot['pending_confirmation_run_id'] = runId;
        } else if (action == 'resumed' ||
            action == 'completed' ||
            action == 'failed' ||
            action == 'cancelled') {
          final pending =
              _runsSnapshot['pending_confirmation_run_id']?.toString() ?? '';
          if (pending == runId) {
            _runsSnapshot['pending_confirmation_run_id'] = '';
          }
        }
      }
    } catch (_) {}

    notifyListeners();
  }

  void _applyOrchestratorSnapshot(Map<String, dynamic> snapshot) {
    final projects = snapshot['projects'];
    _orchestratorProjects = projects is List
        ? projects.map((e) => Map<String, dynamic>.from(e as Map)).toList()
        : [];

    final approvals = snapshot['pending_approvals'];
    _orchestratorApprovals = approvals is List
        ? approvals.map((e) => Map<String, dynamic>.from(e as Map)).toList()
        : [];

    _orchestratorStepsByProject.clear();
    final stepsByProject = snapshot['steps_by_project'];
    if (stepsByProject is Map) {
      stepsByProject.forEach((k, v) {
        final projectId = k.toString();
        if (v is List) {
          _orchestratorStepsByProject[projectId] = v
              .map((e) => Map<String, dynamic>.from(e as Map))
              .toList();
        }
      });
    }

    _orchestratorMissingInputs.clear();
    final missingInputs = snapshot['missing_inputs'];
    if (missingInputs is Map) {
      missingInputs.forEach((k, v) {
        final projectId = k.toString();
        if (v is List) {
          _orchestratorMissingInputs[projectId] = v
              .map((e) => e.toString())
              .toList();
        }
      });
    }
  }

  void _upsertOrchestratorProject(Map<String, dynamic> project) {
    final id = project['id']?.toString() ?? '';
    if (id.isEmpty) return;
    final idx = _orchestratorProjects.indexWhere(
      (p) => p['id']?.toString() == id,
    );
    if (idx >= 0) {
      _orchestratorProjects[idx] = {..._orchestratorProjects[idx], ...project};
      return;
    }
    _orchestratorProjects.add(project);
  }

  void _upsertOrchestratorStep(Map<String, dynamic> step) {
    final projectId = step['project_id']?.toString() ?? '';
    final id = step['id']?.toString() ?? '';
    if (projectId.isEmpty || id.isEmpty) return;
    final list = _orchestratorStepsByProject.putIfAbsent(
      projectId,
      () => <Map<String, dynamic>>[],
    );
    final idx = list.indexWhere((s) => s['id']?.toString() == id);
    if (idx >= 0) {
      list[idx] = {...list[idx], ...step};
    } else {
      list.add(step);
    }
    list.sort((a, b) {
      final ao = (a['order_index'] as num?)?.toInt() ?? 0;
      final bo = (b['order_index'] as num?)?.toInt() ?? 0;
      return ao.compareTo(bo);
    });
  }

  void _applyOrchestratorUpdate(Map<String, dynamic> data) {
    final projectRaw = data['project'];
    if (projectRaw is Map) {
      _upsertOrchestratorProject(Map<String, dynamic>.from(projectRaw));
    }

    final stepRaw = data['step'];
    if (stepRaw is Map) {
      _upsertOrchestratorStep(Map<String, dynamic>.from(stepRaw));
    }

    final action = data['action']?.toString() ?? '';
    if (action == 'approval_decided') {
      final stepId = (data['step'] as Map?)?['id']?.toString() ?? '';
      if (stepId.isNotEmpty) {
        _orchestratorApprovals.removeWhere(
          (a) => a['step_id']?.toString() == stepId,
        );
      }
    }

    if (action == 'input_set') {
      final projectId = data['project_id']?.toString() ?? '';
      final key = data['key']?.toString() ?? '';
      if (projectId.isNotEmpty && key.isNotEmpty) {
        final existing =
            _orchestratorMissingInputs[projectId] ?? const <String>[];
        _orchestratorMissingInputs[projectId] = existing
            .where((e) => e.toLowerCase() != key.toLowerCase())
            .toList();
      }
    }
  }

  void _applyOrchestratorRequest(Map<String, dynamic> data) {
    final kind = data['kind']?.toString() ?? '';
    final projectId = data['project_id']?.toString() ?? '';
    if (projectId.isEmpty) return;

    final stepRaw = data['step'];
    if (stepRaw is Map) {
      _upsertOrchestratorStep(Map<String, dynamic>.from(stepRaw));
    }

    if (kind == 'missing_input') {
      final missing = data['missing'];
      if (missing is List) {
        final merged = <String, String>{};
        for (final v
            in (_orchestratorMissingInputs[projectId] ?? const <String>[])) {
          merged[v.toLowerCase()] = v;
        }
        for (final v in missing) {
          final s = v.toString();
          if (s.isEmpty) continue;
          merged[s.toLowerCase()] = s;
        }
        final list = merged.values.toList()
          ..sort((a, b) => a.toLowerCase().compareTo(b.toLowerCase()));
        _orchestratorMissingInputs[projectId] = list;
      }
      return;
    }

    if (kind == 'approval') {
      final stepId = data['step_id']?.toString() ?? '';
      final reason = data['reason']?.toString() ?? '';
      if (stepId.isEmpty) return;
      _orchestratorApprovals.removeWhere(
        (a) => a['step_id']?.toString() == stepId,
      );
      _orchestratorApprovals.add({
        'id': '',
        'project_id': projectId,
        'step_id': stepId,
        'reason': reason,
        'status': 'pending',
        'created_at': DateTime.now().toIso8601String(),
      });
    }
  }

  void _handleA2UIRender(Map<String, dynamic> data) {
    final viewJson = data['view'];
    if (viewJson is! Map) return;
    final view = A2UIView.fromJson(Map<String, dynamic>.from(viewJson));
    if (view.id.isEmpty) return;

    _a2uiViews.removeWhere((v) => v.id == view.id);
    _a2uiViews.add(view);
    _a2uiViews.sort((a, b) => b.priority.compareTo(a.priority));
    notifyListeners();
  }

  void _handleA2UIUpdate(Map<String, dynamic> data) {
    _handleA2UIRender(data);
  }

  void _handleA2UIClear(Map<String, dynamic> data) {
    final ids = data['view_ids'];
    if (ids is List) {
      _a2uiViews.removeWhere((v) => ids.contains(v.id));
      notifyListeners();
    }
  }

  void _handleA2UIToast(Map<String, dynamic> data) {
    final message = data['message'] as String? ?? '';
    if (message.isNotEmpty) {
      _addMessage('system', message);
    }
  }

  bool hasA2UIView({String? category, String? kind}) {
    return _a2uiViews.any((view) {
      final metaCategory = view.meta['category'];
      final matchesCategory = category == null
          ? true
          : metaCategory == category;
      final matchesKind = kind == null ? true : view.kind == kind;
      return matchesCategory && matchesKind;
    });
  }

  void _handleWindowControl(String action) async {
    // Same as before
    switch (action) {
      case 'minimize':
        await windowManager.minimize();
        break;
      case 'restore':
        await windowManager.restore();
        break;
      case 'close':
        await windowManager.close();
        break;
      case 'show':
        if (await windowManager.isMinimized()) await windowManager.restore();
        await windowManager.show();
        await windowManager.focus();
        break;
    }
  }

  void _addMessage(String role, String text, {bool isPartial = false}) {
    if (text.isEmpty) return;
    _messages.add({
      'role': role,
      'content': text,
      'isPartial': isPartial,
      'timestamp': DateTime.now().toIso8601String(),
    });
    if (_messages.length > 50) _messages.removeAt(0);
    notifyListeners();
  }
}
