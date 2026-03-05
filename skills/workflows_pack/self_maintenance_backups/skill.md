---
name: workflow self maintenance backups
description: Schedules weekly self-maintenance backups, creates zip artifacts, and quarantines old backups instead of deleting.
triggers:
  - set up self maintenance backups
  - setup self maintenance backups
  - schedule weekly backups
  - run self maintenance backups
  - backup workflow now
command: python {SKILL_DIR}/self_maintenance_backups.py --request "{request}"
args:
  - request
type: shell
requires-bin:
  - python
metadata:
  policy:
    risk: low
    requires_confirmation: false
    requires_internet: false
---
