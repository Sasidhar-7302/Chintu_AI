# os focus
Description: Minimizes windows, sets system volume to 25%, opens Spotify, and launches Visual Studio Code for focus mode.
Triggers: focus protocol, os sovereign, i need to focus.*minimize all open windows.*spotify.*visual studio code, minimize all open windows set system volume to 25 open spotify launch visual studio code
Command: python {SKILL_DIR}/os_focus.py
Type: shell
Requires-Bin: python
