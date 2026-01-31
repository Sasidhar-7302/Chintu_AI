# Calendar Pack

# Google Calendar CLI
Description: Manage Google Calendar via gcalcli.
Triggers: calendar, gcal, schedule meeting
Command: gcalcli {args}
Args: args
Type: shell
Requires-Bin: gcalcli
Requires-Env: GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET

# Windows Calendar (open app)
Description: Open Windows Calendar.
Triggers: windows calendar, open calendar
Command: cmd /c start "" "outlookcal:"
Type: shell
Requires-Bin: cmd
