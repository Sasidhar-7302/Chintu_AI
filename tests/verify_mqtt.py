
import sys
import os
import time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from chintu_backend.distributed.mqtt_client import MqttClient

def test_mqtt():
    print("Testing MQTT Client (Paho v2)...")
    client = MqttClient(client_id="test_client_v2")
    
    # We expect this to execute without crashing, even if connection fails (no broker running)
    client.connect()
    print("Connect method called successfully.")
    
    time.sleep(1)
    client.disconnect()
    print("Disconnect called successfully.")
    print("MQTT Module: PASS")

if __name__ == "__main__":
    test_mqtt()
