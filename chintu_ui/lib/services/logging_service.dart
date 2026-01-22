import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:path_provider/path_provider.dart';

class LoggingService {
  static LoggingService? _instance;
  static LoggingService get instance => _instance ??= LoggingService._();

  LoggingService._();

  File? _logFile;
  String _sessionId = '';

  Future<void> init() async {
    try {
      final appDir = await getApplicationDocumentsDirectory();
      final logsDir = Directory('${appDir.path}/Chintu/logs');
      if (!await logsDir.exists()) {
        await logsDir.create(recursive: true);
      }

      _sessionId = DateTime.now().toIso8601String().replaceAll(':', '-');
      _logFile = File('${logsDir.path}/session_$_sessionId.log');
      await _logFile!.writeAsString('=== Chintu Session Started: $_sessionId ===\n');
      
      log('LoggingService', 'Session initialized');
    } catch (e) {
      debugPrint('Failed to initialize logging: $e');
    }
  }

  Future<void> log(String source, String message, {String level = 'INFO'}) async {
    final timestamp = DateTime.now().toIso8601String();
    final logLine = '[$timestamp] [$level] [$source] $message\n';
    
    debugPrint(logLine.trim());
    
    try {
      await _logFile?.writeAsString(logLine, mode: FileMode.append);
    } catch (e) {
      debugPrint('Failed to write log: $e');
    }
  }

  Future<void> logError(String source, String message, [dynamic error, StackTrace? stackTrace]) async {
    await log(source, '$message\nError: $error\nStack: $stackTrace', level: 'ERROR');
  }

  Future<void> logWarning(String source, String message) async {
    await log(source, message, level: 'WARNING');
  }

  Future<String?> getLogPath() async {
    return _logFile?.path;
  }

  Future<List<String>> getRecentLogs({int lines = 100}) async {
    if (_logFile == null || !await _logFile!.exists()) {
      return [];
    }
    try {
      final content = await _logFile!.readAsString();
      final allLines = content.split('\n');
      return allLines.length > lines 
          ? allLines.sublist(allLines.length - lines)
          : allLines;
    } catch (e) {
      return [];
    }
  }

  Future<List<FileSystemEntity>> getAllSessionLogs() async {
    try {
      final appDir = await getApplicationDocumentsDirectory();
      final logsDir = Directory('${appDir.path}/Chintu/logs');
      if (!await logsDir.exists()) return [];
      return logsDir.listSync()..sort((a, b) => b.path.compareTo(a.path));
    } catch (e) {
      return [];
    }
  }
}

// Global logger shortcut
LoggingService get logger => LoggingService.instance;

