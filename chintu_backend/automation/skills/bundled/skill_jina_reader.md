# jina reader
Description: Fetch a clean, readable version of a web page via Jina AI Reader. Use url=...
Triggers: jina reader url=, clean url url=, readable page url=
Command: powershell -NoProfile -Command "$u='{url}'.Trim(); $u=$u -replace '^https?://',''; Invoke-RestMethod -Uri ('https://r.jina.ai/http://' + $u)"
Args: url
Type: shell
Requires-Bin: powershell
