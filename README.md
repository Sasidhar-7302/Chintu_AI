# Chintu AI Assistant v5.1

<p align="center">
  <img src="chintu_ui/assets/branding/Chintu_Logo.png" alt="Chintu Logo" width="150"/>
</p>

<p align="center">
  <b>A voice-controlled, privacy-first AI assistant for Windows.</b>
  <br/>
  Neuro-Symbolic Architecture · Multi-Model Swarm · 75 Capabilities
</p>

<p align="center">
  <a href="#features">Features</a> •
  <a href="INSTALLATION.md">Installation</a> •
  <a href="USAGE.md">Usage</a> •
  <a href="docs/INDEX.md">Full Documentation</a>
</p>

---

## 🌟 Overview

**Chintu v5.1** is a powerful desktop AI assistant featuring a **Neuro-Symbolic Architecture** with a **Federated Swarm Model System**. It combines local wake-word detection, intelligent multi-model LLM routing (Groq/Gemini/Ollama Swarm), semantic memory with 29ms retrieval, and computer vision for complete desktop control.

### Performance Highlights
- ⚡ **Memory Retrieval:** 29ms (31x faster with LRU cache)
- 🧠 **4 Ollama Models:** Router, Planner, Coder, Researcher
- ☁️ **Cloud LLMs:** Groq (~100ms) + Gemini 2.0 Flash
- 🎯 **75 Capabilities** with policy enforcement
- ✅ **100% Test Pass Rate** (16/16 tests)

## ✨ Features

- **🎙️ "Hey Chintu" Activation**: Fast, local wake-word detection with custom ONNX model
- **🧠 Multi-Model Swarm**: 4 specialized Ollama models for routing, planning, coding, and research
- **☁️ Cloud Intelligence**: Groq (fast) + Gemini 2.0 Flash (smart) with automatic fallback
- **👁️ Computer Vision**: Screen analysis with local vision models (Moondream/OmniParser)
- **💾 Semantic Memory**: ChromaDB with LRU caching for 31x faster retrieval
- **🎯 Goal System**: Persistent goals with scheduling (SQLAlchemy 2.0)
- **⚡ App & Web Control**: 75 capabilities for complete desktop automation
- **🔒 Privacy First**: Local-first with optional cloud enhancement
- **🐳 Docker Integration**: Health checks and sandboxing support

---

## 🚀 Quick Start

1.  **Clone** the repository
2.  Run the **Setup**:
    ```powershell
    setup_env.bat
    ```
3.  **Install Ollama Models**:
    ```powershell
    ollama pull qwen2.5:1.5b llama3.1:8b qwen2.5-coder:7b phi3.5:latest
    ```
4.  **Configure API Keys** in `.env`:
    ```env
    GROQ_API_KEY=your_groq_key
    GOOGLE_AI_KEY=your_gemini_key
    ```
5.  **Start** the assistant:
    ```powershell
    Launch-Chintu.ps1
    ```

👉 **[Read the Full Installation Guide](INSTALLATION.md)**

---

## 💡 How to Use

Simply say: **"Hey Chintu..."**

> "Open Spotify and play some jazz."
> "My goal is to learn Python this month."
> "Research the latest AI developments."
> "Write code for a web scraper."
> "What's on my screen right now?"

👉 **[See All 75 Capabilities](USAGE.md)**

---

## 📂 Project Structure

```
Chintu/
├── main.py               # Backend entry point
├── chintu/               # Core AI modules (20+ subpackages)
│   ├── core/             # Config, state, capabilities, routing
│   ├── swarm/            # Multi-model swarm architecture
│   ├── goals/            # Goal system with SQLAlchemy
│   ├── memory/           # ChromaDB + LRU cache
│   └── ...               # Audio, browser, automation, etc.
├── chintu_ui/            # Modern Flutter Desktop UI
├── docs/                 # Complete documentation
├── tests/                # Unit & integration tests
└── Launch-Chintu.ps1    # One-click launcher (PowerShell)
```

---

## 📊 System Requirements

| Component | Requirement |
|-----------|------------|
| **CPU** | Intel Core i5+ |
| **RAM** | 16GB+ (32GB recommended) |
| **GPU** | NVIDIA GTX 1650+ (4GB VRAM) |
| **Storage** | 20GB free space |
| **OS** | Windows 10/11 |

---

*Chintu AI Assistant v5.1 | January 2026*

