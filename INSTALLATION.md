# Installation Guide

This guide will help you set up **Chintu AI** on your Windows machine.

## Prerequisites

Before you begin, ensure you have the following installed:

1.  **Python 3.10 or higher**: [Download here](https://www.python.org/downloads/).
    *   *Note: During installation, check the box "Add Python to PATH".*
2.  **Git**: [Download here](https://git-scm.com/downloads).
3.  **Microphone**: A working microphone is required for voice interaction.

---

## 🚀 Quick Setup (Recommended)

We have provided a one-click setup script to handle everything for you.

1.  **Clone the Repository**
    ```powershell
    git clone https://github.com/Sasidhar-7302/Chintu_AI.git
    cd Chintu_AI
    ```

2.  **Run the Setup Script**
    Simply double-click `setup_env.bat` or run it from the terminal:
    ```powershell
    setup_env.bat
    ```
    *This script will create a virtual environment, install all dependencies, and create a starter configuration file.*

3.  **Configure API Keys**
    *   Open the newly created `.env` file in a text editor (Notepad, VS Code, etc.).
    *   Add your API keys (optional but recommended for intelligence):
        *   **Groq API Key**: Get it free at [console.groq.com](https://console.groq.com)
        *   **Google AI Key**: Get it free at [aistudio.google.com](https://aistudio.google.com)

---

## 🛠️ Manual Installation

If you prefer to set up the environment manually, follow these steps:

1.  **Create a Virtual Environment**
    ```powershell
    python -m venv venv
    ```

2.  **Activate the Environment**
    ```powershell
    venv\Scripts\activate
    ```

3.  **Install Dependencies**
    ```powershell
    pip install -r requirements.txt
    ```

4.  **Create Configuration File**
    Copy `.env.example` to `.env` and fill in your details.
    ```powershell
    copy .env.example .env
    ```

---

## Troubleshooting

### "Python is not recognized..."
Make sure you added Python to your system PATH during installation. You may need to reinstall Python and check that box.

### "Microsoft Visual C++ 14.0 is required"
Some Python packages require build tools. Download and install the [Microsoft C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/).

### Audio Issues
Ensure your default recording device is set correctly in Windows Sound Settings.
