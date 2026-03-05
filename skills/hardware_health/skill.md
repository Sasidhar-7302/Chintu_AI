# hardware health
Description: Reports NVIDIA GPU temps, utilization, VRAM usage, and recommends routing the brain model when idle.
Triggers: hardware health, gpu health, check.*temperature.*vram.*rtx 3060, temperature and vram usage rtx 3060
Command: python {SKILL_DIR}/hardware_health.py
Type: shell
Requires-Bin: python
