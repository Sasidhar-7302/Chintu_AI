
import json
path = r'C:\Users\Sasidhar Yepuri\.chintu\preferences.json'
try:
    with open(path, 'r') as f:
        data = json.load(f)
    
    print(f"Old user_name: {data.get('user_name')}")
    data['user_name'] = 'Sasidhar' # Full name
    
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)
        
    print(f"New user_name: {data.get('user_name')}")
    print("Successfully updated preferences.json")
except Exception as e:
    print(f"Error: {e}")
