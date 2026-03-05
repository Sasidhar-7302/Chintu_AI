import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

class StealthWindowService {
  static const MethodChannel _channel = MethodChannel('chintu/stealth_window');

  static bool get _platformSupported => !kIsWeb;

  static Future<bool> setStealthMode(bool enabled) async {
    if (!_platformSupported) return false;
    try {
      final res = await _channel.invokeMethod<bool>('setStealthMode', enabled);
      return res ?? false;
    } catch (_) {
      return false;
    }
  }

  static Future<bool> isSupported() async {
    if (!_platformSupported) return false;
    try {
      final res = await _channel.invokeMethod<bool>('isSupported');
      return res ?? false;
    } catch (_) {
      return false;
    }
  }
}

