import 'package:flutter/foundation.dart';
import 'package:permission_handler/permission_handler.dart';
import 'logging_service.dart';

class PermissionService extends ChangeNotifier {
  static PermissionService? _instance;
  static PermissionService get instance => _instance ??= PermissionService._();

  PermissionService._();

  bool _microphoneGranted = false;
  bool _cameraGranted = false;
  bool _initialized = false;

  bool get microphoneGranted => _microphoneGranted;
  bool get cameraGranted => _cameraGranted;
  bool get initialized => _initialized;
  bool get allPermissionsGranted => _microphoneGranted && _cameraGranted;

  Future<void> init() async {
    if (_initialized) return;
    
    await checkPermissions();
    _initialized = true;
    logger.log('PermissionService', 'Initialized - Mic: $_microphoneGranted, Camera: $_cameraGranted');
  }

  Future<void> checkPermissions() async {
    try {
      _microphoneGranted = await Permission.microphone.isGranted;
      _cameraGranted = await Permission.camera.isGranted;
      notifyListeners();
      
      logger.log('PermissionService', 'Check - Mic: $_microphoneGranted, Camera: $_cameraGranted');
    } catch (e) {
      logger.logError('PermissionService', 'Error checking permissions', e);
    }
  }

  Future<bool> requestMicrophone() async {
    try {
      logger.log('PermissionService', 'Requesting microphone permission...');
      
      final status = await Permission.microphone.request();
      _microphoneGranted = status.isGranted;
      notifyListeners();
      
      logger.log('PermissionService', 'Microphone permission: $status');
      return _microphoneGranted;
    } catch (e) {
      logger.logError('PermissionService', 'Error requesting microphone', e);
      return false;
    }
  }

  Future<bool> requestCamera() async {
    try {
      logger.log('PermissionService', 'Requesting camera permission...');
      
      final status = await Permission.camera.request();
      _cameraGranted = status.isGranted;
      notifyListeners();
      
      logger.log('PermissionService', 'Camera permission: $status');
      return _cameraGranted;
    } catch (e) {
      logger.logError('PermissionService', 'Error requesting camera', e);
      return false;
    }
  }

  Future<Map<String, bool>> requestAllPermissions() async {
    logger.log('PermissionService', 'Requesting all permissions...');
    
    final mic = await requestMicrophone();
    final camera = await requestCamera();
    
    return {
      'microphone': mic,
      'camera': camera,
    };
  }

  Future<void> openSettings() async {
    logger.log('PermissionService', 'Opening app settings...');
    await openAppSettings();
  }
}

// Global permission service shortcut
PermissionService get permissions => PermissionService.instance;

