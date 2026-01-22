# Chintu - Personal AI Assistant

<p align="center">
  <img src="chintu_ui/assets/chintu_logo.png" alt="Chintu Logo" width="150"/>
</p>

<p align="center">
  <b>A voice-controlled, privacy-first AI assistant for Windows.</b>
  <br/>
  Create · Control · Automate
</p>

<p align="center">
  <a href="#features">Features</a> •
  <a href="INSTALLATION.md">Installation</a> •
  <a href="USAGE.md">Usage</a> •
  <a href="docs/INDEX.md">Docs</a>
</p>

---

## 🌟 Overview

**Chintu** is a powerful desktop assistant designed to live on your Windows PC. Unlike cloud-only assistants, Chintu runs significantly on-device, offering privacy and speed. It combines local wake-word detection, smart LLM routing (Groq/Gemini/Ollama), and computer vision to help you control your digital life.

## ✨ Features

- **🎙️ "Hey Chintu" Activation**: Fast, local wake-word detection.
- **🧠 Smart Intelligence**: Intelligently routes queries to the best model (Fast vs Smart) or runs completely offline with Ollama.
- **👁️ Computer Vision**: "Look" at your screen to find buttons and click them using local vision models.
- **💾 Long-Term Memory**: Remembers your preferences, notes, and past conversations.
- **⚡ App & Web Control**: Launch apps, close windows, and browse the web with voice commands.
- **🔒 Privacy First**: Your data stays yours. Configurable to use local-only models.

---

## 🚀 Quick Start

1.  **Download** the repository.
2.  Run the **One-Click Setup**:
    ```powershell
    setup_env.bat
    ```
3.  **Start** the assistant:
    ```powershell
    start_chintu.bat
    ```

👉 **[Read the Full Installation Guide](INSTALLATION.md)**

---

## 💡 How to Use

Simply say: **"Hey Chintu..."**

> "Open Spotify and play some jazz."
> "Remind me to submit the report in 2 hours."
> "What's on my screen right now?"
> "Taking a note: Buy milk and eggs."

👉 **[See All Voice Commands](USAGE.md)**

---

## 📂 Project Structure

```
Chimptu/
├── main.py               # Backend entry point
├── chintu/               # Core AI modules (Brain, Ears, Voice)
├── chintu_ui/            # Modern Flutter Desktop UI
├── docs/                 # Detailed documentation
├── tests/                # Unit tests
└── setup_env.bat         # Installation script
```

## 🤝 Contributing

Contributions are welcome! Please check the `docs/` folder for architectural details before submitting a Pull Request.

## License

**Private Project - All Rights Reserved.**
Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.
