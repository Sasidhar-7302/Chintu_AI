# module installer
Description: Installs a missing pip package and optionally reruns a Python script to verify.
Triggers: modulenotfounderror.*pandas, module not found pandas, fix module error, install pandas then run script again, pip install package
Command: python {SKILL_DIR}/install_module.py --request {request}
Args: request
Type: shell
Requires-Bin: python
