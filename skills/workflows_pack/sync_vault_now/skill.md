---
name: workflow sync vault now
description: Runs one immediate Markdown vault sync into memory and stores a sync report.
triggers:
  - sync my vault now
  - sync vault now
  - run markdown memory sync
  - obsidian sync now
command: python {SKILL_DIR}/sync_vault_now.py
type: shell
requires-bin:
  - python
metadata:
  policy:
    risk: low
    requires_confirmation: false
    requires_internet: false
---
