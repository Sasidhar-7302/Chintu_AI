
import logging
import sys

# Configure logging
logging.basicConfig(level=logging.INFO)

try:
    from chintu.platform.app_discovery import get_app_discovery, DiscoveredApp
    
    ad = get_app_discovery()
    ad.initialize()
    
    query = "google chromee"
    print(f"Testing find_app('{query}')...")
    
    app = ad.find_app(query)
    
    if app:
        print(f"Found match: {app}")
        print(f"Attempting to open...")
        success = ad.open_app(app)
        print(f"Open result: {success}")
    else:
        print("No match found.")
        
except Exception as e:
    print(f"Error: {e}")
