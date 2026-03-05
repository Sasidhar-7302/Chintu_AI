---
name: workflow email triage daily
description: Creates daily email draft replies as Markdown and can schedule the triage workflow.
triggers:
  - set up daily email triage
  - setup daily email triage
  - schedule email triage
  - run email triage daily
  - email draft replies workflow
command: python {SKILL_DIR}/email_triage_daily.py --request "{request}"
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
