# User Guide

Welcome to **Chintu AI**! This guide covers how to start and interact with your new personal assistant.

## Starting the Assistant

There are two ways to launch Chintu.

### Option 1: The Easy Way (Batch Script)
Double-click `start_chintu.bat`. 
*   This will launch the backend server and the Flutter UI automatically.

### Option 2: Command Line
Open your terminal in the project folder and run:
```powershell
venv\Scripts\activate
python main.py
```

---

## 🎙️ Voice Commands

Once the application is running, simply say **"Hey Chintu"** to wake it up. Wait for the listening tone or visual indicator, then speak your command.

### Core Commands
| Command | Description |
| :--- | :--- |
| **"Hey Chintu"** | Activates the assistant. |
| **"Stop"** or **"Cancel"** | Stops the current action or response. |
| **"Help"** | Lists available capabilities. |

### Productivity
*   "Take a note: [content]"
*   "Remind me to [task] in [time]" (e.g., "Remind me to call John in 10 minutes")
*   "What time is it?"
*   "What is today's date?"

### App & Web Control
*   "Open [Application Name]" (e.g., "Open Notepad", "Open Spotify")
*   "Close [Application Name]"
*   "Open [Website]" (e.g., "Open YouTube", "Go to Google")
*   "Search for [query]"

### Memory & Personalization
*   "My name is [Name]"
*   "Remember that [fact]" (e.g., "Remember that I like pizza")
*   "What do you know about me?"
*   "Forget everything you know about me" (Use with caution!)

### Visual Automation (Experimental)
*   "Click the [text/icon] button"
*   "Find the [text/icon]"

---

## ⚙️ Configuration

You can tweak settings in your `.env` file:

*   **WAKE_WORD_SENSITIVITY**: Adjust between 0.0 (strict) and 1.0 (sensitive) if it triggers too often or not enough.
*   **TTS_AUTO_SPEAK**: Set to `True` if you want Chintu to always read responses out loud.

---

## Keyboard Shortcuts (UI)

*   **Esc**: Minimize to tray
*   **Ctrl + Q**: Quit application
