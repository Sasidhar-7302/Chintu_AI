
import os
import sys

path = r'chintu_ui/lib/services/websocket_service.dart'

try:
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Define the new method body
    new_method = '''  void _handleWindowControl(String action) async {
    debugPrint('Window control: ' + action);
    switch (action) {
      case 'minimize':
      case 'send_to_back':
        await windowManager.minimize();
        break;
      case 'maximize':
        await windowManager.maximize();
        break;
      case 'restore':
        await windowManager.restore();
        break;
      case 'close':
        await windowManager.close();
        break;
      case 'show':
      case 'bring_to_front':
        if (await windowManager.isMinimized()) {
           await windowManager.restore();
        }
        await windowManager.show();
        await windowManager.focus();
        break;
      case 'hide':
        await windowManager.hide();
        break;
    }
  }'''

    # Find the old method and replace it
    # We look for the signature "void _handleWindowControl(String action)" 
    # and replace until the end of the class "}"
    
    match_str = "void _handleWindowControl(String action)"
    if match_str in content:
        start_idx = content.rfind(match_str)
        # Find the end of the class to verify we are replacing correctly
        end_class_idx = content.rfind("}")
        
        # We replace from start_idx up to (but not including) the last closing brace of the class?
        # No, the method has a closing brace too.
        
        # Simpler: The file ends with "}}" (method close, class close) or similar.
        # Let's just strip the existing method if we can identify it, or just append if it wasn't there (but it is).
        
        # Let's replace the previous simple implementation:
        # "void _handleWindowControl(String action) { print('Window control: ' + action); }"
        # OR the complex one if it partially applied.
        
        # Best bet: Regex replacement of the whole function block
        import re
        # Match "void _handleWindowControl... }" allowing for newlines and nested braces? 
        # Dart braces are balanced.
        
        # Let's use a split strategy.
        parts = content.split("void _handleWindowControl(String action)")
        if len(parts) > 1:
            pre = parts[0]
            # The part after might contain the body and then other stuff (though it's the last method).
            # The file ends with:
            #   }
            # }
            
            # Use the fact it's the last method before the final '}'
            # We reconstruct the file as: pre + new_method + "\n}"
            
            final_content = pre + new_method + "\n}"
            
            with open(path, 'w', encoding='utf-8') as f:
                f.write(final_content)
            print("Successfully patched via split/join")
        else:
            print("Method signature not found for splitting")
            
    else:
        print("Method not found for patching")

except Exception as e:
    print(f"Error: {e}")
