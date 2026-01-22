"""
Home Assistant Integration for Chintu AI Assistant.

Provides smart home control via Home Assistant REST API:
- Control lights, switches, scenes
- Query device states
- Automation triggers

No heavy LLM needed - just API calls.
"""

import os
import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


class HomeAssistant:
    """
    Home Assistant integration via REST API.
    
    Requires:
    1. Home Assistant instance (local or cloud)
    2. Long-Lived Access Token from HA
    """
    
    def __init__(
        self,
        url: Optional[str] = None,
        token: Optional[str] = None
    ):
        """
        Initialize Home Assistant client.
        
        Args:
            url: Home Assistant URL (e.g., http://192.168.1.100:8123)
            token: Long-Lived Access Token
        """
        self.url = url or os.environ.get('HOME_ASSISTANT_URL', '')
        self.token = token or os.environ.get('HOME_ASSISTANT_TOKEN', '')
        
        self._headers = {
            'Authorization': f'Bearer {self.token}',
            'Content-Type': 'application/json',
        }
        
    @property
    def is_configured(self) -> bool:
        """Check if Home Assistant is configured."""
        return bool(self.url and self.token)
    
    def _request(self, method: str, endpoint: str, data: Optional[Dict] = None) -> Optional[Dict]:
        """Make API request to Home Assistant."""
        if not HAS_REQUESTS:
            raise ImportError("requests library not installed")
            
        if not self.is_configured:
            raise RuntimeError("Home Assistant not configured. Set URL and token.")
        
        url = f"{self.url.rstrip('/')}/api/{endpoint}"
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=self._headers, timeout=10)
            elif method == 'POST':
                response = requests.post(url, headers=self._headers, json=data, timeout=10)
            else:
                raise ValueError(f"Unsupported method: {method}")
            
            response.raise_for_status()
            return response.json() if response.text else {}
            
        except requests.RequestException as e:
            logger.error(f"Home Assistant request failed: {e}")
            return None
    
    def get_states(self) -> List[Dict[str, Any]]:
        """Get all entity states."""
        result = self._request('GET', 'states')
        return result if isinstance(result, list) else []
    
    def get_state(self, entity_id: str) -> Optional[Dict[str, Any]]:
        """Get state of a specific entity."""
        return self._request('GET', f'states/{entity_id}')
    
    def turn_on(self, entity_id: str) -> bool:
        """Turn on an entity (light, switch, etc.)."""
        domain = entity_id.split('.')[0]
        result = self._request('POST', f'services/{domain}/turn_on', {
            'entity_id': entity_id
        })
        return result is not None
    
    def turn_off(self, entity_id: str) -> bool:
        """Turn off an entity."""
        domain = entity_id.split('.')[0]
        result = self._request('POST', f'services/{domain}/turn_off', {
            'entity_id': entity_id
        })
        return result is not None
    
    def toggle(self, entity_id: str) -> bool:
        """Toggle an entity."""
        domain = entity_id.split('.')[0]
        result = self._request('POST', f'services/{domain}/toggle', {
            'entity_id': entity_id
        })
        return result is not None
    
    def set_light_brightness(self, entity_id: str, brightness: int) -> bool:
        """Set light brightness (0-255)."""
        result = self._request('POST', 'services/light/turn_on', {
            'entity_id': entity_id,
            'brightness': min(255, max(0, brightness))
        })
        return result is not None
    
    def set_light_color(self, entity_id: str, rgb: tuple) -> bool:
        """Set light color (R, G, B)."""
        result = self._request('POST', 'services/light/turn_on', {
            'entity_id': entity_id,
            'rgb_color': list(rgb)
        })
        return result is not None
    
    def activate_scene(self, scene_id: str) -> bool:
        """Activate a scene."""
        result = self._request('POST', 'services/scene/turn_on', {
            'entity_id': scene_id
        })
        return result is not None
    
    def get_devices_by_type(self, domain: str) -> List[Dict[str, Any]]:
        """Get all devices of a specific type (light, switch, climate, etc.)."""
        states = self.get_states()
        return [s for s in states if s['entity_id'].startswith(f'{domain}.')]
    
    def get_lights(self) -> List[Dict[str, Any]]:
        """Get all lights."""
        return self.get_devices_by_type('light')
    
    def get_switches(self) -> List[Dict[str, Any]]:
        """Get all switches."""
        return self.get_devices_by_type('switch')
    
    def find_entity(self, name: str) -> Optional[str]:
        """
        Find entity by friendly name.
        
        Args:
            name: Friendly name to search for
            
        Returns:
            entity_id if found, None otherwise
        """
        name_lower = name.lower()
        states = self.get_states()
        
        for state in states:
            entity_id = state['entity_id']
            friendly_name = state.get('attributes', {}).get('friendly_name', '')
            
            # Check matches
            if name_lower in friendly_name.lower():
                return entity_id
            if name_lower in entity_id.lower():
                return entity_id
                
        return None
    
    def format_status(self, entities: List[Dict]) -> str:
        """Format device status for voice output."""
        if not entities:
            return "No devices found."
            
        lines = []
        for entity in entities[:5]:  # Limit for voice
            name = entity.get('attributes', {}).get('friendly_name', entity['entity_id'])
            state = entity['state']
            lines.append(f"{name} is {state}")
            
        return ". ".join(lines)


# Global instance
_ha: Optional[HomeAssistant] = None


def get_home_assistant() -> HomeAssistant:
    """Get or create the global Home Assistant instance."""
    global _ha
    if _ha is None:
        _ha = HomeAssistant()
    return _ha
