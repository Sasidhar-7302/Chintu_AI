# Home / IoT Pack

# Home Assistant
Description: Call Home Assistant REST API (requires HASS URL/token).
Triggers: home assistant, hass, smart home
Command: python -m chintu_backend.integrations.home_assistant "{query}"
Args: query
Type: shell
Requires-Env: HASS_URL, HASS_TOKEN
