"""Simple WebSocket server test."""
import asyncio
import json
import websockets

async def handler(websocket):
    print(f"Client connected")
    try:
        # Send initial state
        await websocket.send(json.dumps({
            "type": "state_update",
            "data": {
                "assistant_state": "idle",
                "transcript": "",
                "audio_level": 0.0,
            }
        }))
        
        # Handle messages
        async for message in websocket:
            print(f"Received: {message}")
            data = json.loads(message)
            
            if data.get("type") == "command":
                text = data.get("text", "")
                print(f"Command: {text}")
                
                # Echo back as response
                await websocket.send(json.dumps({
                    "type": "response",
                    "text": f"You said: {text}"
                }))
    except websockets.exceptions.ConnectionClosed:
        print("Client disconnected")

async def main():
    print("Starting WebSocket server on ws://127.0.0.1:8765")
    async with websockets.serve(handler, "127.0.0.1", 8765):
        print("Server is running! Press Ctrl+C to stop.")
        await asyncio.Future()  # run forever

if __name__ == "__main__":
    asyncio.run(main())
