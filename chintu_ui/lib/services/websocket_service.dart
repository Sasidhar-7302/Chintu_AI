import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:web_socket_channel/io.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:window_manager/window_manager.dart';

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
  String _lastResponse = '';
  String _lastCommand = '';
  List<bool> _wakeWordSamples = List<bool>.filled(5, false);
  int _wakeWordSampleCount = 5;
  String _wakeWordTrainingStatus = '';
  String _wakeWordTrainingMessage = '';
  int? _wakeWordRecordingIndex;
  bool _greetingSent = false;

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

  Future<void> connect({String host = '127.0.0.1', int port = 8765}) async {
    await _tryConnect(host, port);
  }

  Future<void> _tryConnect(String host, int port) async {
    try {
      final socket = await WebSocket.connect('ws://$host:$port');
      _channel = IOWebSocketChannel(socket);
      _channel!.stream.listen(
        _onMessage,
        onError: (error) => _handleDisconnect(host, port),
        onDone: () => _handleDisconnect(host, port),
      );
      _isConnected = true;
      _sendGreeting();
      notifyListeners();
    } catch (e) {
      _isConnected = false;
      notifyListeners();
      _scheduleReconnect(host, port);
    }
  }

  void _sendGreeting() {
    if (!_greetingSent) {
      _greetingSent = true;
      /* Hardcoded greeting removed - Backend now sends dynamic greeting
      _messages.add({
        'role': 'assistant',
        'content': 'Hello Sasidhar! I am Chintu, your personal AI assistant. Say "Hey Chintu" to wake me up, or type a command below.',
      });
      */
    }
  }

  void _handleDisconnect(String host, int port) {
    _isConnected = false;
    notifyListeners();
    _scheduleReconnect(host, port);
  }

  void _scheduleReconnect(String host, int port) {
    _reconnectTimer?.cancel();
    _reconnectTimer = Timer(const Duration(seconds: 2), () => _tryConnect(host, port));
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
          if (text.isNotEmpty) _addMessage('assistant', text);
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
        case 'error':
          _handleError(message['data'] as Map<String, dynamic>? ?? {});
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
      }).toList();
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
      
      // Update existing assistant bubble if it exists
      if (_messages.isNotEmpty && _messages.last['role'] == 'assistant') {
          _messages.last['content'] = lastResponse;
      } else {
          _addMessage('assistant', lastResponse);
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

  void _addMessage(String role, String text, {bool isPartial = false}) {
    if (text.isEmpty) return;
    _messages.add({'role': role, 'content': text, 'isPartial': isPartial, 'timestamp': DateTime.now().toIso8601String()});
    if (_messages.length > 50) _messages.removeAt(0);
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
