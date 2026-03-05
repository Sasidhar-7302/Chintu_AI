import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';

import 'package:chintu_ui/screens/splash_screen.dart';
import 'package:chintu_ui/services/websocket_service.dart';
import 'package:chintu_ui/theme/app_theme.dart';
import 'package:chintu_ui/widgets/dashboard_panel.dart';

void main() {
  testWidgets('Splash screen shows title and completes init flow', (WidgetTester tester) async {
    var completed = false;
    await tester.pumpWidget(
      MaterialApp(
        home: SplashScreen(onComplete: () => completed = true),
      ),
    );

    expect(find.text('CHINTU'), findsOneWidget);
    expect(completed, isFalse);

    // Splash sequence is 1s + 1s + 0.5s.
    await tester.pump(const Duration(milliseconds: 2600));
    expect(completed, isTrue);
  });

  testWidgets('Dashboard exposes Models and Identity tabs', (WidgetTester tester) async {
    final ws = WebSocketService(autoConnect: false);
    await tester.pumpWidget(
      ChangeNotifierProvider<WebSocketService>.value(
        value: ws,
        child: MaterialApp(
          theme: AppTheme.dark(),
          home: const Scaffold(body: DashboardPanel()),
        ),
      ),
    );

    expect(find.text('Tasks'), findsOneWidget);
    expect(find.text('Review'), findsOneWidget);
    expect(find.text('Models'), findsOneWidget);
    expect(find.text('Identity'), findsOneWidget);

    await tester.tap(find.text('Models'));
    await tester.pumpAndSettle();
    expect(find.text('Model Runtime'), findsOneWidget);

    await tester.tap(find.text('Identity'));
    await tester.pumpAndSettle();
    expect(find.text('Identity Runtime'), findsOneWidget);

    await tester.tap(find.text('Links'));
    await tester.pumpAndSettle();
    expect(find.text('OAuth Control Center'), findsOneWidget);
  });

  testWidgets('Dashboard renders in narrow viewport without exceptions', (WidgetTester tester) async {
    final ws = WebSocketService(autoConnect: false);
    await tester.binding.setSurfaceSize(const Size(390, 844));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    await tester.pumpWidget(
      ChangeNotifierProvider<WebSocketService>.value(
        value: ws,
        child: MaterialApp(
          theme: AppTheme.dark(),
          home: const Scaffold(body: DashboardPanel()),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Operations'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
