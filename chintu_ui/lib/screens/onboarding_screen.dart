import 'package:flutter/material.dart';

import '../services/onboarding_service.dart';
import '../theme/app_theme.dart';

class OnboardingScreen extends StatefulWidget {
  final VoidCallback onComplete;

  const OnboardingScreen({super.key, required this.onComplete});

  @override
  State<OnboardingScreen> createState() => _OnboardingScreenState();
}

class _OnboardingScreenState extends State<OnboardingScreen> {
  final _userController = TextEditingController(text: 'User');
  final _assistantController = TextEditingController(text: 'Chintu');
  bool _telegramEnabled = true;
  bool _saving = false;

  @override
  void dispose() {
    _userController.dispose();
    _assistantController.dispose();
    super.dispose();
  }

  Future<void> _finish() async {
    if (_saving) {
      return;
    }
    setState(() => _saving = true);
    await OnboardingService.markComplete(
      userName: _userController.text,
      assistantName: _assistantController.text,
      telegramEnabled: _telegramEnabled,
    );
    if (!mounted) {
      return;
    }
    widget.onComplete();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.background,
      body: Container(
        decoration: const BoxDecoration(gradient: AppTheme.appBackground),
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 760),
            child: Padding(
              padding: const EdgeInsets.all(20),
              child: DecoratedBox(
                decoration: BoxDecoration(
                  color: AppColors.surface,
                  borderRadius: BorderRadius.circular(18),
                  border: Border.all(color: AppColors.border),
                ),
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(24, 22, 24, 20),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'Welcome to Chintu',
                        style: TextStyle(
                          color: AppColors.textPrimary,
                          fontSize: 24,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                      const SizedBox(height: 8),
                      const Text(
                        'Complete this once, then Chintu opens directly into the workspace.',
                        style: TextStyle(
                          color: AppColors.textMuted,
                          fontSize: 13,
                        ),
                      ),
                      const SizedBox(height: 18),
                      TextField(
                        controller: _userController,
                        decoration: const InputDecoration(
                          labelText: 'Your name',
                          hintText: 'User',
                        ),
                      ),
                      const SizedBox(height: 10),
                      TextField(
                        controller: _assistantController,
                        decoration: const InputDecoration(
                          labelText: 'Assistant name',
                          hintText: 'Chintu',
                        ),
                      ),
                      const SizedBox(height: 10),
                      Row(
                        children: [
                          Switch(
                            value: _telegramEnabled,
                            onChanged: (value) =>
                                setState(() => _telegramEnabled = value),
                          ),
                          const SizedBox(width: 8),
                          const Expanded(
                            child: Text(
                              'I will use Telegram remote control',
                              style: TextStyle(
                                color: AppColors.textPrimary,
                                fontSize: 13,
                              ),
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 12),
                      const Text(
                        'Checklist',
                        style: TextStyle(
                          color: AppColors.textPrimary,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                      const SizedBox(height: 8),
                      const Text(
                        '1) Run scripts\\setup_env.bat once\n'
                        '2) Configure .env (or use Chintu CLI onboard)\n'
                        '3) Start backend with scripts\\start_chintu.bat',
                        style: TextStyle(
                          color: AppColors.textMuted,
                          fontSize: 12.5,
                          height: 1.45,
                        ),
                      ),
                      const SizedBox(height: 18),
                      Align(
                        alignment: Alignment.centerRight,
                        child: ElevatedButton.icon(
                          onPressed: _saving ? null : _finish,
                          icon: _saving
                              ? const SizedBox(
                                  width: 14,
                                  height: 14,
                                  child: CircularProgressIndicator(
                                    strokeWidth: 2,
                                    color: Colors.black,
                                  ),
                                )
                              : const Icon(Icons.arrow_forward_rounded),
                          label: Text(_saving ? 'Saving...' : 'Continue'),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

