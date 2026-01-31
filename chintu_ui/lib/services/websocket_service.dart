import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:flutter/foundation.dart';
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
  String _lastResponse = '';
  String _lastCommand = '';
  List<bool> _wakeWordSamples = List<bool>.filled(5, false);
  int _wakeWordSampleCount = 5;
  String _wakeWordTrainingStatus = '';
  String _wakeWordTrainingMessage = '';
  int? _wakeWordRecordingIndex;
  bool _greetingSent = false;
  String _targetHost = '127.0.0.1';
  int? _targetPort;
  String _resolvedHost = '127.0.0.1';
  int _resolvedPort = 8765;
  final List<A2UIView> _a2uiViews = [];
  bool _triedDefaultPort = false;
  Map<String, dynamic> _hud = {};

  WebSocketService() { connect(); }

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
  String get wakeWordTrainingStatus => _wakeWordTrainingStatus;
  String get wakeWordTrainingMessage => _wakeWordTrainingMessage;
  int? get wakeWordRecordingIndex => _wakeWordRecordingIndex;
  String get resolvedHost => _resolvedHost;
  int get resolvedPort => _resolvedPort;
  bool get usingAutoPort => _targetPort == null;
  List<A2UIView> get a2uiViews => List.unmodifiable(_a2uiViews);
  List<Map<String, String>> get activityLog => _activityLog;
  List<Map<String, dynamic>> get backendLogs => List.unmodifiable(_backendLogs);
  List<Map<String, dynamic>> get scheduledTasks => _scheduledTasks;
  Map<String, dynamic> get hud => _hud;

  bool hasA2UIView({String? kind, String? category}) {
    for (final view in _a2uiViews) {
      if (kind != null && kind.isNotEmpty && view.kind == kind) {
        return true;
      }
      if (category != null && category.isNotEmpty) {
        final metaCategory = view.meta['category']?.toString() ?? '';
        if (metaCategory == category) {
          return true;
        }
      }
    }
    return false;
  }

  Future<void> connect({String host = '127.0.0.1', int? port}) async {
    _targetHost = host;
    _targetPort = port;
    _triedDefaultPort = false;
    final resolved = await _resolveEndpoint();
    await _tryConnect(resolved.host, resolved.port);
  }

  Future<void> _tryConnect(String host, int port) async {
    try {
      final socket = await WebSocket.connect('ws://$host:$port');
      _channel = IOWebSocketChannel(socket);
      _channel!.stream.listen(
        _onMessage,
        onError: (error) => _handleDisconnect(),
        onDone: () => _handleDisconnect(),
      );
      _isConnected = true;
      _lastResponse = '';
      _lastCommand = '';
      _messages.clear();
      _sendClientCapabilities();
      _sendGreeting();
      notifyListeners();
    } catch (e) {
      _isConnected = false;
      notifyListeners();
      if (_targetPort == null && !_triedDefaultPort && port != 8765) {
        _triedDefaultPort = true;
        _resolvedHost = host;
        _resolvedPort = 8765;
        notifyListeners();
        await _tryConnect(host, 8765);
        return;
      }
      _scheduleReconnect();
    }
  }

  void _sendClientCapabilities() {
    if (!_isConnected || _channel == null) return;
    try {
      _channel!.sink.add(jsonEncode({
        'type': 'client_capabilities',
        'data': {
          'a2ui': {
            'supported': true,
            'schema_version': 'a2ui-1.0',
          },
          'platform': Platform.operatingSystem,
        },
      }));
    } catch (_) {
      // Best-effort capability registration.
    }
  }

  void _sendGreeting() {
    if (!_greetingSent) {
      _greetingSent = true;
      // No hardcoded greeting - backend sends the exact greeting from logs
      // The greeting will appear via 'response' message type or 'state_update' with last_response
    }
  }

  void _handleDisconnect() {
    _isConnected = false;
    notifyListeners();
    _scheduleReconnect();
  }

  void _scheduleReconnect() {
    _reconnectTimer?.cancel();
    _reconnectTimer = Timer(const Duration(seconds: 2), () => _retryConnect());
  }

  // Code Approval Stream
  final _approvalRequestController = StreamController<Map<String, dynamic>>.broadcast();
  Stream<Map<String, dynamic>> get approvalRequests => _approvalRequestController.stream;

  @override
  void dispose() {
    _approvalRequestController.close();
    _reconnectTimer?.cancel();
    _channel?.sink.close();
    super.dispose();
  }

  void _onMessage(dynamic data) {
    try {
      final message = jsonDecode(data as String) as Map<String, dynamic>;
      final type = message['type'] as String?;

      switch (type) {
        case 'state_update':
          _handleStateUpdate(message['data'] as Map<String, dynamic>? ?? {});
          break;
        case 'status':
          _status = message['status'] as String? ?? 'idle';
          break;
        case 'audio_level':
          _audioLevel = (message['level'] as num?)?.toDouble() ?? 0.0;
          break;
        case 'transcript':
          _transcript = message['text'] as String? ?? '';
          if (_transcript.isNotEmpty) _addMessage('user', _transcript);
          break;
        case 'response':
          final text = message['text'] as String? ?? '';
          if (text.isNotEmpty) {
            // Ensure we don't duplicate the greeting - check if it's already in messages
            final isDuplicate = _messages.any((msg) => 
              msg['role'] == 'assistant' && msg['content'] == text
            );
            if (!isDuplicate) {
              _addMessage('assistant', text);
            }
          }
          break;
        case 'gesture':
          _gesture = message['gesture'] as String? ?? '';
          break;
        case 'capabilities':
          _capabilities = List<Map<String, dynamic>>.from(message['capabilities'] as List? ?? []);
          break;
        case 'wake_word_status':
          _handleWakeWordStatus(message);
          break;
        case 'wake_word_sample':
          _handleWakeWordSample(message);
          break;
        case 'wake_word_training':
          _handleWakeWordTraining(message);
          break;
        case 'window_control':
          _handleWindowControl(message['action'] as String? ?? '');
          break;
        case 'code_approval_request':
          _approvalRequestController.add(message);
          break;
        case 'a2ui_render':
          _handleA2UIRender(message['data'] as Map<String, dynamic>? ?? {});
          break;
        case 'a2ui_update':
          _handleA2UIRender(message['data'] as Map<String, dynamic>? ?? {});
          break;
        case 'a2ui_clear':
          _handleA2UIClear(message['data'] as Map<String, dynamic>? ?? {});
          break;
        case 'a2ui_toast':
          _handleA2UIToast(message['data'] as Map<String, dynamic>? ?? {});
          break;
        case 'a2ui_action_result':
          _handleA2UIActionResult(message['data'] as Map<String, dynamic>? ?? {});
          break;
        case 'error':
          _handleError(message['data'] as Map<String, dynamic>? ?? {});
          break;
        case 'log_event':
          _handleLogEvent(message['data'] as Map<String, dynamic>? ?? {});
          break;
      }
      notifyListeners();
    } catch (e) {
      debugPrint('Error parsing message: $e');
    }
  }

  void sendCodeApprovalResponse(String requestId, bool approved) {
    if (_isConnected && _channel != null) {
      _channel!.sink.add(jsonEncode({
        'type': 'code_approval_response',
        'request_id': requestId,
        'approved': approved
      }));
    }
  }

  Future<void> sendA2UIAction(
    String viewId,
    String actionId, {
    Map<String, dynamic>? payload,
    Map<String, dynamic>? form,
  }) async {
    if (!_isConnected || _channel == null) return;
    final data = encodeA2UIActionPayload(
      viewId: viewId,
      actionId: actionId,
      payload: payload,
      form: form,
    );
    _channel!.sink.add(data);
  }

  void _handleStateUpdate(Map<String, dynamic> data) {
    _status = (data['assistant_state'] as String?) ?? (data['status'] as String?) ?? _status;
    _audioLevel = (data['audio_level'] as num?)?.toDouble() ?? _audioLevel;
    _transcript = data['transcript'] as String? ?? _transcript;

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
        return {
          'id': entry.key,
          'name': value['name'] ?? entry.key,
          'enabled': enabled,
          'status': status,
          'active': enabled && status == 'active',
        };
      }).toList();
    }
    
    // Parse Control Center Data
    final logs = data['activity_log'] as List?;
    if (logs != null) {
      _activityLog = logs.map((e) => Map<String, String>.from(e)).toList();
    }
    
    final tasks = data['scheduled_tasks'] as List?;
    if (tasks != null) {
      _scheduledTasks = tasks.map((e) => Map<String, dynamic>.from(e)).toList();
    }

    final hudData = data['hud'] as Map<String, dynamic>?;
    if (hudData != null) {
      _hud = Map<String, dynamic>.from(hudData);
    }

    // Refined Fix: Streaming updates for USER
    final lastCmd = data['last_command'] as String? ?? '';
    
    // A. Handle Final Command
    if (lastCmd.isNotEmpty && lastCmd != _lastCommand) {
      _lastCommand = lastCmd;
      
      // Check if we have a partial message to finalize
      if (_messages.isNotEmpty && _messages.last['role'] == 'user' && _messages.last['isPartial'] == true) {
        _messages.last['content'] = lastCmd;
        _messages.last['isPartial'] = false;
      } else {
        _addMessage('user', lastCmd);
      }
    } 
    // B. Handle Partial Streaming (Transcript)
    else if (_transcript.isNotEmpty && _status == 'listening' && lastCmd.isEmpty) {
      // If last message is partial user msg, update it
      if (_messages.isNotEmpty && _messages.last['role'] == 'user' && _messages.last['isPartial'] == true) {
         _messages.last['content'] = _transcript;
      } else {
         // Create new partial bubble
         _addMessage('user', _transcript, isPartial: true);
      }
    }

    // Refined Fix: Streaming updates for ASSISTANT
    final lastResponse = data['last_response'] as String? ?? '';
    if (lastResponse.isNotEmpty && lastResponse != _lastResponse) {
      _lastResponse = lastResponse;
      
      // Update existing assistant bubble if it exists, or add new one if not duplicate
      if (_messages.isNotEmpty && _messages.last['role'] == 'assistant') {
          // Only update if content is different to avoid duplicates
          if (_messages.last['content'] != lastResponse) {
            _messages.last['content'] = lastResponse;
          }
      } else {
          // Check for duplicates before adding
          final isDuplicate = _messages.any((msg) => 
            msg['role'] == 'assistant' && msg['content'] == lastResponse
          );
          if (!isDuplicate) {
            _addMessage('assistant', lastResponse);
          }
      }
    }
  }

  void _handleWakeWordStatus(Map<String, dynamic> message) {
    _wakeWordSampleCount = message['count'] as int? ?? _wakeWordSampleCount;
    final samples = message['samples'] as List?;
    if (samples != null) {
      final parsed = samples.map((s) => s as bool).toList();
      _wakeWordSamples = [...parsed, ...List<bool>.filled(_wakeWordSampleCount - parsed.length, false)];
    } else {
      _wakeWordSamples = List<bool>.filled(_wakeWordSampleCount, false);
    }
  }

  void _handleWakeWordSample(Map<String, dynamic> message) {
    final index = message['index'] as int? ?? 0;
    final status = message['status'] as String? ?? '';
    if (index > 0 && index <= _wakeWordSamples.length && status == 'recorded') {
      _wakeWordSamples[index - 1] = true;
    }
    if (status == 'error') {
      _wakeWordTrainingStatus = 'error';
      _wakeWordTrainingMessage = message['message'] as String? ?? 'Recording failed.';
    }
    if (_wakeWordRecordingIndex == index) _wakeWordRecordingIndex = null;
  }

  void _handleWakeWordTraining(Map<String, dynamic> message) {
    _wakeWordTrainingStatus = message['status'] as String? ?? '';
    _wakeWordTrainingMessage = message['message'] as String? ?? '';
    if (_wakeWordTrainingStatus == 'completed' || _wakeWordTrainingStatus == 'error') {
      _wakeWordRecordingIndex = null;
    }
  }

  void _handleError(Map<String, dynamic> data) {
    final severity = (data['severity'] as String? ?? 'error').toUpperCase();
    final component = data['component'] as String? ?? 'system';
    final message = data['message'] as String? ?? 'An unexpected error occurred.';
    _addMessage('system', '[$severity] $component: $message');
  }

  void _handleLogEvent(Map<String, dynamic> data) {
    _backendLogs.add(data);
    if (_backendLogs.length > 500) {
      _backendLogs.removeAt(0);
    }
    notifyListeners();
  }

  void _handleA2UIRender(Map<String, dynamic> data) {
    final viewJson = data['view'];
    if (viewJson is! Map) return;
    final view = A2UIView.fromJson(Map<String, dynamic>.from(viewJson));
    if (view.id.isEmpty) return;

    _a2uiViews.removeWhere((v) => v.id == view.id);
    _a2uiViews.add(view);
    _a2uiViews.sort((a, b) {
      final priorityCmp = b.priority.compareTo(a.priority);
      if (priorityCmp != 0) return priorityCmp;
      final aTime = a.createdAt?.millisecondsSinceEpoch ?? 0;
      final bTime = b.createdAt?.millisecondsSinceEpoch ?? 0;
      return bTime.compareTo(aTime);
    });
  }

  void _handleA2UIClear(Map<String, dynamic> data) {
    final ids = <String>{};
    final single = data['view_id']?.toString();
    if (single != null && single.isNotEmpty) ids.add(single);
    final list = data['view_ids'];
    if (list is List) {
      for (final item in list) {
        final id = item?.toString() ?? '';
        if (id.isNotEmpty) ids.add(id);
      }
    }
    if (ids.isEmpty) return;
    _a2uiViews.removeWhere((v) => ids.contains(v.id));
  }

  void _handleA2UIToast(Map<String, dynamic> data) {
    final severity = (data['severity'] as String? ?? 'info').toUpperCase();
    final message = data['message'] as String? ?? '';
    if (message.isNotEmpty) {
      _addMessage('system', '[$severity] $message');
    }
  }

  void _handleA2UIActionResult(Map<String, dynamic> data) {
    final success = data['success'] as bool? ?? false;
    final message = data['message'] as String? ?? '';
    if (message.isNotEmpty) {
      final prefix = success ? '[A2UI OK]' : '[A2UI]';
      _addMessage('system', '$prefix $message');
    }
  }

  void _addMessage(String role, String text, {bool isPartial = false}) {
    if (text.isEmpty) return;
    _messages.add({'role': role, 'content': text, 'isPartial': isPartial, 'timestamp': DateTime.now().toIso8601String()});
    if (_messages.length > 50) _messages.removeAt(0);
  }

  Future<void> _retryConnect() async {
    final resolved = await _resolveEndpoint();
    await _tryConnect(resolved.host, resolved.port);
  }

  Future<_ResolvedEndpoint> _resolveEndpoint() async {
    var host = _targetHost;
    var port = _targetPort ?? 8765;

    if (_targetPort == null) {
      final portFile = await _readPortFile();
      if (portFile != null) {
        final fileHost = portFile['host'] as String?;
        final filePort = portFile['port'];
        if (_targetHost == '127.0.0.1' && fileHost != null && fileHost.isNotEmpty) {
          host = fileHost;
        }
        if (filePort is int) {
          port = filePort;
        } else if (filePort is String) {
          final parsed = int.tryParse(filePort);
          if (parsed != null) {
            port = parsed;
          }
        }
      }
    }

    final changed = _resolvedHost != host || _resolvedPort != port;
    _resolvedHost = host;
    _resolvedPort = port;
    if (changed) {
      notifyListeners();
    }

    return _ResolvedEndpoint(host, port);
  }

  Future<Map<String, dynamic>?> _readPortFile() async {
    try {
      final path = _getPortFilePath();
      if (path == null || path.isEmpty) {
        return null;
      }
      final file = File(path);
      if (!await file.exists()) {
        return null;
      }
      final content = await file.readAsString();
      final data = jsonDecode(content);
      if (data is Map<String, dynamic>) {
        return data;
      }
    } catch (e) {
      debugPrint('Failed to read WebSocket port file: $e');
    }
    return null;
  }

  String? _getPortFilePath() {
    final home = Platform.environment['USERPROFILE'] ?? Platform.environment['HOME'];
    if (home == null || home.isEmpty) {
      return null;
    }
    return '$home${Platform.pathSeparator}.chintu${Platform.pathSeparator}ws_port.json';
  }
  void startPushToTalk() {
    if (_isConnected && _channel != null) {
      _channel!.sink.add(jsonEncode({'type': 'push_to_talk', 'action': 'start'}));
    }
  }

  void stopPushToTalk() {
    if (_isConnected && _channel != null) {
      _channel!.sink.add(jsonEncode({'type': 'push_to_talk', 'action': 'stop'}));
    }
  }

  void sendCommand(String command) {
    if (_isConnected && _channel != null) {
      _channel!.sink.add(jsonEncode({'type': 'command', 'text': command}));
      _lastCommand = command;
      _addMessage('user', command);
      notifyListeners();
    }
  }

  void requestWakeWordStatus() {
    if (_isConnected && _channel != null) {
      _channel!.sink.add(jsonEncode({'type': 'get_wake_word_status'}));
    }
  }

  void recordWakeWordSample(int index) {
    if (_isConnected && _channel != null) {
      _wakeWordRecordingIndex = index;
      _channel!.sink.add(jsonEncode({'type': 'record_wake_word_sample', 'index': index, 'kind': 'positive'}));
      notifyListeners();
    }
  }

  void trainWakeWord() {
    if (_isConnected && _channel != null) {
      _wakeWordTrainingStatus = 'started';
      _wakeWordTrainingMessage = 'Training started.';
      _channel!.sink.add(jsonEncode({'type': 'wake_word_train'}));
      notifyListeners();
    }
  }

  void _handleWindowControl(String action) async {
    debugPrint('Window control: $action');
    switch (action) {
      case 'minimize':
      case 'send_to_back':
        await windowManager.minimize();
        break;
      case 'maximize':
        await windowManager.maximize();
        break;
      case 'restore':
        await windowManager.restore();
        break;
      case 'close':
        await windowManager.close();
        break;
      case 'show':
      case 'bring_to_front':
        if (await windowManager.isMinimized()) {
           await windowManager.restore();
        }
        await windowManager.show();
        await windowManager.focus();
        break;
      case 'hide':
        await windowManager.hide();
        break;
    }
  }
}

class _ResolvedEndpoint {
  final String host;
  final int port;

  const _ResolvedEndpoint(this.host, this.port);
}
