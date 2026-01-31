# searxng
Description: Web search via a self-hosted SearXNG instance (no API key). Use query=... (URL will be encoded).
Triggers: searxng query=, web search searxng query=
Command: powershell -NoProfile -Command "$q=[uri]::EscapeDataString('{query}'); $url=\"$env:SEARXNG_URL/search?q=$q&format=json\"; Invoke-RestMethod -Uri $url | ConvertTo-Json -Depth 5"
Args: query
Type: shell
Requires-Bin: powershell
Requires-Env: SEARXNG_URL
