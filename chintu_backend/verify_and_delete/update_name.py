
import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

from chintu_backend.brain.memory.preferences import get_preference_manager
from chintu_backend.core.command_handler import CommandHandler # Ensure config loaded

try:
    pm = get_preference_manager()
    old = pm.preferences.user_name
    print(f"Old name: {old}")
    
    pm.preferences.user_name = "Sasidhar"
    pm.save()
    
    print(f"New name: {pm.preferences.user_name}")
    print("Preferences updated successfully.")
except Exception as e:
    print(f"Error: {e}")
