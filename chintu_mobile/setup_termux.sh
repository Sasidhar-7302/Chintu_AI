#!/bin/bash
# Chintu Mobile Agent - Termux Setup Script
# Run this on your Android phone in Termux

echo "========================================"
echo "   Chintu Mobile Agent Setup"
echo "========================================"
echo ""

# Update packages
echo "[1/6] Updating Termux packages..."
pkg update -y && pkg upgrade -y

# Install required packages
echo ""
echo "[2/6] Installing Python, SSH, and Node.js..."
pkg install -y python openssh nodejs git

# Install Python dependencies
echo ""
echo "[3/6] Installing Python packages..."
pip install flask requests

# Install PM2 for process management
echo ""
echo "[4/6] Installing PM2..."
npm install -g pm2

# Setup SSH
echo ""
echo "[5/6] Setting up SSH server..."
echo "Please set a password for SSH access:"
passwd

# Start SSH server
sshd

# Get device info
echo ""
echo "[6/6] Setup complete!"
echo ""
echo "========================================"
echo "   Connection Information"
echo "========================================"
echo ""
echo "SSH Port: 8022"
echo "Username: $(whoami)"
echo "IP Address: $(ip route | grep wlan0 | grep -oP 'src \K[\d.]+')"
echo ""
echo "========================================"
echo ""
echo "To connect from your laptop:"
echo "  ssh -p 8022 $(whoami)@<your-ip>"
echo ""
echo "Or say 'Hey Chintu, scan for devices'"
echo ""
echo "To keep SSH running when Termux is closed:"
echo "  termux-wake-lock"
echo ""
echo "Setup complete! Your phone is ready to connect."
