# caffeine
Description: Keep the PC awake by starting/stopping Windows Presentation Settings. Use with args=/start or args=/stop.
Triggers: caffeine args=, keep awake args=
Command: presentationsettings {args}
Args: args
Type: shell
Requires-Bin: presentationsettings
