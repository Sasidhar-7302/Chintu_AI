---
name: workflow background health checks
description: Schedules daily background health checks and can run one immediately to write a Markdown health report.
triggers:
  - set up background health checks
  - setup background health checks
  - schedule daily health checks
  - run background health checks
  - health check workflow
command: python {SKILL_DIR}/background_health_checks.py --request "{request}"
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
