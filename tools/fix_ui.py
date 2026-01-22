
import os

def fix_websocket_service():
    path = r"c:\Users\Sasidhar Yepuri\Desktop\My_Projects\Chimptu\chintu_ui\lib\services\websocket_service.dart"
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Target the problematic block
        old_block = """    if (_status != 'listening' && _transcript.isNotEmpty && _transcript != _lastCommand) {
      _addMessage('user', _transcript);
      _lastCommand = _transcript;
    }"""
        
        # New block using last_command
        new_block = """    // Fix: Only add message when 'last_command' changes (is final)
    final lastCmd = data['last_command'] as String? ?? '';
    if (lastCmd.isNotEmpty && lastCmd != _lastCommand) {
      _lastCommand = lastCmd;
      _addMessage('user', lastCmd);
    }"""
        
        # Also fix the duplicate transcript handler in _onMessage if possible
        # but the main issue is _handleStateUpdate being too aggressive.
        
        if old_block in content:
            content = content.replace(old_block, new_block)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            print("Fixed websocket_service.dart")
        else:
            # Try to handle potential whitespace differences by normalizing spaces?
            # Or just warn.
            print("Could not find target block in websocket_service.dart. Checking for near matches...")
            # Fallback: simple replacement of the condition line?
            if "_transcript != _lastCommand)" in content:
                 print("Found partial match, attempting patch...")
                 # This is risky without seeing exact content, but let's try strict first.
            else:
                 print("No match found.")

    except Exception as e:
        print(f"Error fixing websocket_service.dart: {e}")

def fix_home_screen():
    path = r"c:\Users\Sasidhar Yepuri\Desktop\My_Projects\Chimptu\chintu_ui\lib\screens\home_screen.dart"
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # 1. Add import
        if "import '../widgets/ai_orb.dart';" in content and "import '../widgets/waveform_widget.dart';" not in content:
            content = content.replace(
                "import '../widgets/ai_orb.dart';", 
                "import '../widgets/ai_orb.dart';\nimport '../widgets/waveform_widget.dart';"
            )
            
        # 2. Replace AIOrb with conditional Waveform
        old_widget = "AIOrb(state: state, audioLevel: audioLevel, size: 200),"
        new_widget = """(state == 'listening' || state == 'speaking')
                      ? SizedBox(height: 200, child: WaveformWidget(audioLevel: audioLevel, isActive: true))
                      : AIOrb(state: state, audioLevel: audioLevel, size: 200),"""
        
        if old_widget in content:
            content = content.replace(old_widget, new_widget)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            print("Fixed home_screen.dart")
        else:
            print("Could not find AIOrb widget in home_screen.dart")

    except Exception as e:
        print(f"Error fixing home_screen.dart: {e}")

if __name__ == "__main__":
    fix_websocket_service()
    fix_home_screen()
