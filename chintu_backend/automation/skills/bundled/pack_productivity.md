# Productivity Pack

# Notion
Description: Create or search notes in Notion (requires Notion token).
Triggers: notion, notion note, notion search
Command: python -m chintu_backend.skills.tools.notion "{query}"
Args: query
Type: shell
Requires-Env: NOTION_TOKEN

# Obsidian
Description: Open or create a note in Obsidian via URI.
Triggers: obsidian, obsidian note
Command: cmd /c start "" "obsidian://new?file={file}"
Args: file
Type: shell
Requires-Bin: cmd

# OneNote
Description: Open OneNote (Windows).
Triggers: onenote, open onenote
Command: cmd /c start "" "onenote:"
Type: shell
Requires-Bin: cmd

# Trello
Description: Create or list Trello cards via CLI (trello-cli).
Triggers: trello, trello card
Command: trello {args}
Args: args
Type: shell
Requires-Bin: trello

# GitHub (gh CLI)
Description: Create/list issues or PRs using GitHub CLI.
Triggers: github, gh issue, gh pr
Command: gh {args}
Args: args
Type: shell
Requires-Bin: gh
