
import logging
import sys
import os
import time

# Add project root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

logging.basicConfig(level=logging.INFO)

def test_ui_control():
    print("Testing UI/Screen Control...")
    try:
        from chintu_backend.automation.screen_control import get_screen_controller
        
        controller = get_screen_controller()
        if not controller.enabled:
            print("FAIL: PyAutoGUI not enabled/installed.")
            return

        print("Moving mouse in a square pattern...")
        start_pos = controller.get_mouse_position()
        print(f"Start Position: {start_pos}")
        
        # Move 50px right
        controller.click_at(start_pos[0] + 50, start_pos[1], clicks=0) # Just move
        time.sleep(0.5)
        # Move 50px down
        controller.click_at(start_pos[0] + 50, start_pos[1] + 50, clicks=0)
        time.sleep(0.5)
        # Move 50px left
        controller.click_at(start_pos[0], start_pos[1] + 50, clicks=0)
        time.sleep(0.5)
        # Move back
        controller.click_at(start_pos[0], start_pos[1], clicks=0)
        
        print("PASS: Mouse movement commands sent.")
        
    except ImportError as e:
        print(f"Import Error: {e}")
    except Exception as e:
        print(f"Runtime Error: {e}")

if __name__ == "__main__":
    test_ui_control()
