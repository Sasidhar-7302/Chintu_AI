import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:window_manager/window_manager.dart';
import 'services/websocket_service.dart';
import 'services/logging_service.dart';
import 'services/onboarding_service.dart';
import 'services/permission_service.dart';
import 'screens/terminal_screen.dart';
import 'screens/splash_screen.dart';
import 'screens/home_screen_clean.dart';
import 'screens/onboarding_screen.dart';
import 'theme/app_theme.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  await windowManager.ensureInitialized();
  const windowOptions = WindowOptions(
    size: Size(1200, 720),
    center: true,
    backgroundColor: Colors.transparent,
    titleBarStyle: TitleBarStyle.hidden,
    alwaysOnTop: false,
  );
  windowManager.waitUntilReadyToShow(windowOptions, () async {
    await windowManager.show();
    await windowManager.focus();
  });

  // Initialize logging
  await LoggingService.instance.init();
  logger.log('Main', 'Chintu starting...');

  // Initialize permission service
  await PermissionService.instance.init();

  runApp(const ChintuApp());
}

class ChintuApp extends StatefulWidget {
  const ChintuApp({super.key});

  @override
  State<ChintuApp> createState() => _ChintuAppState();
}

class _ChintuAppState extends State<ChintuApp> {
  int _currentIndex = 1; // Start with SplashScreen
  bool _onboardingStateLoaded = false;
  bool _onboardingRequired = false;

  @override
  void initState() {
    super.initState();
    NavRelay.onNavigate = (index) => setState(() => _currentIndex = index);
    _loadOnboardingState();
  }

  Future<void> _loadOnboardingState() async {
    final done = await OnboardingService.isComplete();
    if (!mounted) return;
    setState(() {
      _onboardingStateLoaded = true;
      _onboardingRequired = !done;
    });
  }

  void _onInitializationComplete() {
    if (!_onboardingStateLoaded) {
      Future<void>.delayed(const Duration(milliseconds: 150), () {
        if (mounted) {
          _onInitializationComplete();
        }
      });
      return;
    }
    setState(() {
      _currentIndex = _onboardingRequired ? 3 : 0;
    });
  }

  void _onOnboardingComplete() {
    setState(() {
      _onboardingRequired = false;
      _currentIndex = 0;
    });
  }

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        ChangeNotifierProvider(create: (_) => WebSocketService()),
        ChangeNotifierProvider.value(value: PermissionService.instance),
      ],
      child: MaterialApp(
        title: 'Chintu AI Assistant',
        debugShowCheckedModeBanner: false,
        theme: AppTheme.dark(),
        home: Scaffold(
          body: Builder(
            builder: (context) {
              return IndexedStack(
                index: _currentIndex,
                children: [
                  const HomeScreenClean(),
                  SplashScreen(onComplete: _onInitializationComplete),
                  TerminalScreen(
                    onBack: () => setState(() => _currentIndex = 0),
                  ),
                  OnboardingScreen(onComplete: _onOnboardingComplete),
                ],
              );
            },
          ),
        ),
      ),
    );
  }
}

// Global navigation relay (simple approach for this project)
class NavRelay {
  static void Function(int)? onNavigate;
}
