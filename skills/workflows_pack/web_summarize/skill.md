---
name: workflow web summarize
description: Summarizes a URL into a saved Markdown artifact for later querying.
triggers:
  - /summarize
  - summarize this url
  - summarize this website
  - web summarize
  - save web summary
command: python {SKILL_DIR}/web_summarize.py --request "{request}"
args:
  - request
type: shell
requires-bin:
  - python
metadata:
  policy:
    risk: low
    requires_confirmation: false
    requires_internet: true
---
