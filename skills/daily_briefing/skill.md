---
name: daily briefing
description: Builds a fresh daily briefing with calendar plus 20 high-signal headlines, then supports "read more" follow-ups.
triggers:
  - daily briefing
  - morning briefing
  - good morning
  - google calendar for today
  - top headlines today
  - read more about headline
  - briefing details
command: python {SKILL_DIR}/daily_briefing.py "{request}"
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
