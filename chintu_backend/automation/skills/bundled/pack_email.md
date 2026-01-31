# Email Pack

# IMAP Email (himalaya)
Description: Read or send email using Himalaya CLI (IMAP/SMTP).
Triggers: email, inbox, send email
Command: himalaya {args}
Args: args
Type: shell
Requires-Bin: himalaya

# Outlook Desktop
Description: Open Outlook (Windows).
Triggers: outlook, open outlook
Command: cmd /c start "" "outlook"
Type: shell
Requires-Bin: cmd
