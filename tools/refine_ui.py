
import os

def refine_websocket_service():
    path = r"c:\Users\Sasidhar Yepuri\Desktop\My_Projects\Chimptu\chintu_ui\lib\services\websocket_service.dart"
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()

        # ---------------------------------------------------------
        # 1. Update User Logic (Transcription Streaming)
        # ---------------------------------------------------------
        
        # This is the block we added in the previous fix (simple version)
        user_target_block = """    // Fix: Only add message when 'last_command' changes (is final)
    final lastCmd = data['last_command'] as String? ?? '';
    if (lastCmd.isNotEmpty && lastCmd != _lastCommand) {
      _lastCommand = lastCmd;
      _addMessage('user', lastCmd);
    }"""

        # New sophisticated logic for USER
        user_new_logic = """    // Refined Fix: Streaming updates for USER
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
    }"""
        
        # ---------------------------------------------------------
        # 2. Update Assistant Logic (Response Streaming)
        # ---------------------------------------------------------

        assistant_target_block = """    final lastResponse = data['last_response'] as String? ?? '';
    if (lastResponse.isNotEmpty && lastResponse != _lastResponse) {
      _lastResponse = lastResponse;
      _addMessage('assistant', lastResponse);
    }"""

        assistant_new_logic = """    // Refined Fix: Streaming updates for ASSISTANT
    final lastResponse = data['last_response'] as String? ?? '';
    if (lastResponse.isNotEmpty && lastResponse != _lastResponse) {
      _lastResponse = lastResponse;
      
      // Update existing assistant bubble if it exists
      if (_messages.isNotEmpty && _messages.last['role'] == 'assistant') {
          _messages.last['content'] = lastResponse;
      } else {
          _addMessage('assistant', lastResponse);
      }
    }"""

        # ---------------------------------------------------------
        # 3. Update Helper Method Signature
        # ---------------------------------------------------------
        
        signature_target = "void _addMessage(String role, String text)"
        signature_replacement = "void _addMessage(String role, String text, {bool isPartial = false})"
        
        body_target = "_messages.add({'role': role, 'content': text, 'timestamp': DateTime.now().toIso8601String()});"
        body_replacement = "_messages.add({'role': role, 'content': text, 'isPartial': isPartial, 'timestamp': DateTime.now().toIso8601String()});"

        # Apply Replacements
        modified = False
        
        if user_target_block in content:
            content = content.replace(user_target_block, user_new_logic)
            modified = True
            print("Patched User Logic")
        else:
            print("Warning: Could not find User Logic block (already patched?)")

        if assistant_target_block in content:
            content = content.replace(assistant_target_block, assistant_new_logic)
            modified = True
            print("Patched Assistant Logic")
        else:
            print("Warning: Could not find Assistant Logic block")

        if signature_target in content:
            content = content.replace(signature_target, signature_replacement)
            modified = True
            print("Patched _addMessage signature")

        if body_target in content:
            content = content.replace(body_target, body_replacement)
            modified = True
            print("Patched _addMessage body")

        if modified:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            print("Successfully refined websocket_service.dart")
        else:
            print("No changes made to websocket_service.dart")

    except Exception as e:
        print(f"Error refining websocket_service.dart: {e}")

if __name__ == "__main__":
    refine_websocket_service()
