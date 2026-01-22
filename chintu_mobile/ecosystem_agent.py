#!/usr/bin/env python3
"""Chintu Mobile Agent - Full Ecosystem Access

Runs on Android via Termux with Termux:API.
Provides access to: Camera, Mic, Screen, GPS, Battery, Notifications, etc.
"""

import os
import json
import socket
import subprocess
import base64
import time
import logging
from pathlib import Path
from flask import Flask, request, jsonify, send_file

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuration
AGENT_PORT = 5050
TEMP_DIR = Path.home() / "chintu_temp"
TEMP_DIR.mkdir(exist_ok=True)


def run_termux_cmd(cmd: list, timeout: int = 30) -> dict:
    """Run a Termux API command and return result."""
    try:
        result = subprocess.run(
            cmd, 
            capture_output=True, 
            text=True, 
            timeout=timeout
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Command timed out"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================================
# HEALTH & STATUS
# ============================================================================

@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({
        "status": "ok",
        "device": socket.gethostname(),
        "agent": "chintu-ecosystem",
        "version": "2.0"
    })


@app.route("/battery", methods=["GET"])
def battery():
    """Get battery status."""
    result = run_termux_cmd(["termux-battery-status"])
    if result["success"]:
        try:
            data = json.loads(result["stdout"])
            return jsonify(data)
        except:
            return jsonify(result)
    return jsonify(result), 500


@app.route("/device-info", methods=["GET"])
def device_info():
    """Get device information."""
    info = {}
    
    # Get various device properties
    props = {
        "model": "ro.product.model",
        "brand": "ro.product.brand", 
        "android_version": "ro.build.version.release",
        "sdk": "ro.build.version.sdk"
    }
    
    for key, prop in props.items():
        result = subprocess.run(
            ["getprop", prop], 
            capture_output=True, 
            text=True
        )
        info[key] = result.stdout.strip()
    
    return jsonify(info)


# ============================================================================
# CAMERA
# ============================================================================

@app.route("/camera/photo", methods=["POST"])
def take_photo():
    """Take a photo with the camera.
    
    Body: {"camera": 0|1} (0=back, 1=front)
    """
    data = request.json or {}
    camera_id = data.get("camera", 0)
    
    filename = f"photo_{int(time.time())}.jpg"
    filepath = TEMP_DIR / filename
    
    result = run_termux_cmd([
        "termux-camera-photo",
        "-c", str(camera_id),
        str(filepath)
    ], timeout=10)
    
    if result["success"] and filepath.exists():
        # Return base64 encoded image
        with open(filepath, "rb") as f:
            image_data = base64.b64encode(f.read()).decode()
        
        return jsonify({
            "success": True,
            "filename": filename,
            "data": image_data,
            "size": filepath.stat().st_size
        })
    
    return jsonify(result), 500


@app.route("/camera/download/<filename>", methods=["GET"])
def download_photo(filename):
    """Download a captured photo."""
    filepath = TEMP_DIR / filename
    if filepath.exists():
        return send_file(filepath, mimetype="image/jpeg")
    return jsonify({"error": "File not found"}), 404


# ============================================================================
# MICROPHONE
# ============================================================================

@app.route("/mic/record", methods=["POST"])
def record_audio():
    """Record audio from microphone.
    
    Body: {"duration": seconds, "format": "m4a"|"wav"}
    """
    data = request.json or {}
    duration = min(data.get("duration", 5), 60)  # Max 60 seconds
    
    filename = f"audio_{int(time.time())}.m4a"
    filepath = TEMP_DIR / filename
    
    result = run_termux_cmd([
        "termux-microphone-record",
        "-l", str(duration),
        "-f", str(filepath)
    ], timeout=duration + 5)
    
    # Wait for recording to complete
    time.sleep(duration + 1)
    
    # Stop recording
    run_termux_cmd(["termux-microphone-record", "-q"])
    
    if filepath.exists():
        with open(filepath, "rb") as f:
            audio_data = base64.b64encode(f.read()).decode()
        
        return jsonify({
            "success": True,
            "filename": filename,
            "data": audio_data,
            "duration": duration
        })
    
    return jsonify({"success": False, "error": "Recording failed"}), 500


# ============================================================================
# DISPLAY & NOTIFICATIONS
# ============================================================================

@app.route("/display/toast", methods=["POST"])
def show_toast():
    """Show a toast message on screen.
    
    Body: {"message": "text", "position": "top|middle|bottom"}
    """
    data = request.json or {}
    message = data.get("message", "Hello from Chintu!")
    position = data.get("position", "middle")
    
    result = run_termux_cmd([
        "termux-toast",
        "-g", position,
        message
    ])
    
    return jsonify(result)


@app.route("/display/notification", methods=["POST"])
def show_notification():
    """Show a notification.
    
    Body: {"title": "...", "content": "...", "id": 1}
    """
    data = request.json or {}
    title = data.get("title", "Chintu")
    content = data.get("content", "Notification")
    notif_id = data.get("id", "chintu-1")
    
    result = run_termux_cmd([
        "termux-notification",
        "--id", str(notif_id),
        "-t", title,
        "-c", content
    ])
    
    return jsonify(result)


@app.route("/display/brightness", methods=["POST"])
def set_brightness():
    """Set screen brightness.
    
    Body: {"level": 0-255}
    """
    data = request.json or {}
    level = max(0, min(255, data.get("level", 128)))
    
    result = run_termux_cmd([
        "termux-brightness",
        str(level)
    ])
    
    return jsonify(result)


# ============================================================================
# AUDIO OUTPUT (TTS)
# ============================================================================

@app.route("/speak", methods=["POST"])
def speak():
    """Speak text using TTS.
    
    Body: {"text": "...", "rate": 1.0}
    """
    data = request.json or {}
    text = data.get("text", "Hello!")
    rate = data.get("rate", 1.0)
    
    result = run_termux_cmd([
        "termux-tts-speak",
        "-r", str(rate),
        text
    ], timeout=60)
    
    return jsonify(result)


# ============================================================================
# LOCATION
# ============================================================================

@app.route("/location", methods=["GET"])
def get_location():
    """Get current GPS location."""
    result = run_termux_cmd([
        "termux-location",
        "-p", "gps"  # Use GPS provider
    ], timeout=30)
    
    if result["success"]:
        try:
            return jsonify(json.loads(result["stdout"]))
        except:
            pass
    
    return jsonify(result), 500


# ============================================================================
# SENSORS & HARDWARE
# ============================================================================

@app.route("/vibrate", methods=["POST"])
def vibrate():
    """Vibrate the phone.
    
    Body: {"duration": milliseconds}
    """
    data = request.json or {}
    duration = min(data.get("duration", 500), 5000)
    
    result = run_termux_cmd([
        "termux-vibrate",
        "-d", str(duration)
    ])
    
    return jsonify(result)


@app.route("/sensors", methods=["GET"])
def get_sensors():
    """Get sensor data (accelerometer, etc)."""
    result = run_termux_cmd([
        "termux-sensor",
        "-s", "accelerometer",
        "-n", "1"
    ])
    
    if result["success"]:
        try:
            return jsonify(json.loads(result["stdout"]))
        except:
            pass
    
    return jsonify(result)


# ============================================================================
# CLIPBOARD
# ============================================================================

@app.route("/clipboard/get", methods=["GET"])
def get_clipboard():
    """Get clipboard content."""
    result = run_termux_cmd(["termux-clipboard-get"])
    return jsonify({"content": result["stdout"] if result["success"] else ""})


@app.route("/clipboard/set", methods=["POST"])
def set_clipboard():
    """Set clipboard content.
    
    Body: {"content": "..."}
    """
    data = request.json or {}
    content = data.get("content", "")
    
    result = run_termux_cmd(["termux-clipboard-set", content])
    return jsonify(result)


# ============================================================================
# BROWSER / URL
# ============================================================================

@app.route("/browser/open", methods=["POST"])
def open_url():
    """Open a URL in the phone's browser.
    
    Body: {"url": "https://..."}
    """
    data = request.json or {}
    url = data.get("url", "https://google.com")
    
    result = run_termux_cmd(["termux-open-url", url])
    return jsonify(result)


@app.route("/browser/share", methods=["POST"])
def share_text():
    """Share text using Android share menu.
    
    Body: {"text": "...", "title": "..."}
    """
    data = request.json or {}
    text = data.get("text", "")
    title = data.get("title", "Share from Chintu")
    
    result = run_termux_cmd(["termux-share", "-a", "send", text])
    return jsonify(result)


# ============================================================================
# COMMANDS (For ecosystem tasks)
# ============================================================================

@app.route("/command", methods=["POST"])
def execute_command():
    """Execute an allowed command.
    
    Body: {"command": "..."}
    """
    data = request.json or {}
    cmd = data.get("command", "")
    
    # Security: Only allow specific safe commands
    allowed_prefixes = [
        "termux-", "whoami", "pwd", "ls", "cat", "echo",
        "python", "pip", "node", "npm"
    ]
    
    if not any(cmd.startswith(p) for p in allowed_prefixes):
        return jsonify({"error": "Command not allowed"}), 403
    
    result = run_termux_cmd(cmd.split(), timeout=30)
    return jsonify(result)


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    logger.info(f"Starting Chintu Ecosystem Agent on port {AGENT_PORT}")
    logger.info(f"Temp directory: {TEMP_DIR}")
    
    # Show startup notification
    subprocess.run([
        "termux-notification",
        "-t", "Chintu Agent",
        "-c", "Ecosystem agent is running!",
        "--id", "chintu-startup"
    ], capture_output=True)
    
    app.run(host="0.0.0.0", port=AGENT_PORT, debug=False)
