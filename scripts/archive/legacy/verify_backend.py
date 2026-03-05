import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

try:
    print("Attempting to import chintu_backend.automation.calendar_capabilities...")
    import chintu_backend.automation.calendar_capabilities
    print("SUCCESS: calendar_capabilities imported.")
    
    print("Attempting to import chintu_backend.automation.hardware_capabilities...")
    import chintu_backend.automation.hardware_capabilities
    print("SUCCESS: hardware_capabilities imported.")
    
    print("Attempting to import chintu_backend.core.app...")
    import chintu_backend.core.app
    print("SUCCESS: core.app imported.")
    
except Exception as e:
    print(f"FAILURE: {e}")
    sys.exit(1)
