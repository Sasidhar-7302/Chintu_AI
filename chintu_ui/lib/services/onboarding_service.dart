import 'dart:convert';
import 'dart:io';

import 'package:path_provider/path_provider.dart';

class OnboardingService {
  static const String _markerFileName = 'onboarding_complete.json';

  static Future<File> _markerFile() async {
    final dir = await getApplicationSupportDirectory();
    await dir.create(recursive: true);
    return File('${dir.path}${Platform.pathSeparator}$_markerFileName');
  }

  static Future<bool> isComplete() async {
    try {
      final file = await _markerFile();
      return file.existsSync();
    } catch (_) {
      return false;
    }
  }

  static Future<void> markComplete({
    required String userName,
    required String assistantName,
    bool telegramEnabled = false,
  }) async {
    final file = await _markerFile();
    final payload = {
      'completed_at_utc': DateTime.now().toUtc().toIso8601String(),
      'user_name': userName.trim().isEmpty ? 'User' : userName.trim(),
      'assistant_name': assistantName.trim().isEmpty
          ? 'Chintu'
          : assistantName.trim(),
      'telegram_enabled': telegramEnabled,
    };
    await file.writeAsString(
      const JsonEncoder.withIndent('  ').convert(payload),
      flush: true,
    );
  }
}

