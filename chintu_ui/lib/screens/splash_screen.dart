import 'dart:async';

import 'package:flutter/material.dart';

import '../theme/app_theme.dart';

class SplashScreen extends StatefulWidget {
  final VoidCallback onComplete;

  const SplashScreen({super.key, required this.onComplete});

  @override
  State<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends State<SplashScreen> {
  String _status = 'Booting core services...';

  @override
  void initState() {
    super.initState();
    _startSequence();
  }

  Future<void> _startSequence() async {
    await Future<void>.delayed(const Duration(milliseconds: 900));
    if (mounted) setState(() => _status = 'Connecting local gateway...');
    await Future<void>.delayed(const Duration(milliseconds: 850));
    if (mounted) setState(() => _status = 'Preparing workspace...');
    await Future<void>.delayed(const Duration(milliseconds: 700));
    widget.onComplete();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.background,
      body: Container(
        decoration: const BoxDecoration(gradient: AppTheme.appBackground),
        child: Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                width: 106,
                height: 106,
                padding: const EdgeInsets.all(18),
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: AppColors.surfaceStrong,
                  border: Border.all(
                    color: AppColors.accent.withValues(alpha: 0.45),
                    width: 1.4,
                  ),
                  boxShadow: [
                    BoxShadow(
                      color: AppColors.accent.withValues(alpha: 0.12),
                      blurRadius: 18,
                    ),
                  ],
                ),
                child: Image.asset(
                  'assets/branding/ChintuLogo.png',
                  fit: BoxFit.contain,
                  errorBuilder: (context, error, stackTrace) {
                    return const Icon(
                      Icons.bolt_rounded,
                      color: AppColors.accent,
                      size: 40,
                    );
                  },
                ),
              ),
              const SizedBox(height: 28),
              const Text(
                'CHINTU',
                style: TextStyle(
                  color: AppColors.textPrimary,
                  fontSize: 24,
                  fontWeight: FontWeight.w700,
                  letterSpacing: 2.6,
                ),
              ),
              const SizedBox(height: 8),
              Text(
                _status,
                style: const TextStyle(
                  color: AppColors.textMuted,
                  fontSize: 12,
                ),
              ),
              const SizedBox(height: 22),
              Container(
                width: 140,
                height: 2,
                decoration: BoxDecoration(
                  color: AppColors.border,
                  borderRadius: BorderRadius.circular(99),
                ),
                child: const Align(
                  alignment: Alignment.centerLeft,
                  child: SizedBox(
                    width: 58,
                    child: DecoratedBox(
                      decoration: BoxDecoration(
                        color: AppColors.accent,
                        borderRadius: BorderRadius.all(Radius.circular(99)),
                      ),
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
