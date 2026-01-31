# Weather Skill
Description: Get a quick weather summary for a location.
Triggers: weather, forecast
Command: curl "https://wttr.in/{location}?format=3"
Args: location
Type: shell
Requires-Bin: curl

# IP Info
Description: Check public IP and location info.
Triggers: ip info, my ip
Command: curl "https://ipinfo.io"
Type: shell
Requires-Bin: curl
