"""Verify New features (Window Manager, Screen Control, Reader)."""

import sys
import os
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

class TestNewFeatures(unittest.TestCase):
    
    def test_window_manager(self):
        print("\nTesting Window Manager...")
        from chintu_backend.platform.window_manager import get_window_manager
        wm = get_window_manager()
        summary = wm.get_window_summary()
        self.assertIsInstance(summary, str)
        print(f"  Windows detected: {summary}")
        self.assertNotEqual(summary, "", "Should return a summary string")

    def test_screen_control_import(self):
        print("\nTesting Screen Control Implementation...")
        from chintu_backend.automation.screen_control import get_screen_controller
        ctrl = get_screen_controller()
        if ctrl.enabled:
            print("  PyAutoGUI is enabled.")
            # Verify methods exist
            dict_attrs = dir(ctrl)
            self.assertTrue("click_at" in dict_attrs)
            self.assertTrue("type_text" in dict_attrs)
        else:
            print("  PyAutoGUI disabled (safe mode or missing).")

    def test_switch_window(self):
        print("\nTesting Switch Window...")
        from chintu_backend.platform.window_manager import get_window_manager
        wm = get_window_manager()
        # Try finding VS Code (likely open for user)
        res = wm.switch_to_window("code")
        print(f"  Switch to 'code' result: {res}")
        # Try nonsense
        res2 = wm.switch_to_window("xyz123_invalid_app")
        print(f"  Switch to invalid app result: {res2}")
        self.assertFalse(res2)

if __name__ == "__main__":
    unittest.main()
