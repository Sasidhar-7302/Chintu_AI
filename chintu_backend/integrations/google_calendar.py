"""
Google Calendar Integration for Chintu AI Assistant.

Provides calendar management capabilities:
- Read upcoming events
- Create new events
- Search events
- Proactive notifications

Follows tool-first architecture: API calls are cheap, LLM only for summarization.
"""

import os
import logging
import datetime
import json
from typing import Optional, Dict, Any, List
from pathlib import Path

logger = logging.getLogger(__name__)

# OAuth2 support
try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    HAS_GOOGLE_API = True
except ImportError:
    HAS_GOOGLE_API = False
    logger.warning("google-api-python-client not installed - Calendar disabled")


class GoogleCalendar:
    """
    Google Calendar integration.
    
    Requires:
    1. Google Cloud project with Calendar API enabled
    2. OAuth2 credentials (credentials.json)
    
    First run will open browser for authorization.
    """
    
    READ_SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']
    WRITE_SCOPES = ['https://www.googleapis.com/auth/calendar.events']
    
    def __init__(
        self,
        credentials_path: Optional[str] = None,
        token_path: Optional[str] = None,
        scopes: Optional[List[str]] = None,
    ):
        """
        Initialize calendar client.
        
        Args:
            credentials_path: Path to credentials.json from Google Cloud
            token_path: Path to store OAuth token
        """
        self.credentials_path = credentials_path or os.environ.get(
            'GOOGLE_CREDENTIALS_PATH',
            str(Path.home() / '.chintu' / 'credentials.json')
        )
        self.token_path = token_path or str(Path.home() / '.chintu' / 'calendar_token.json')
        self.scopes = list(scopes or self._resolve_scopes_from_env())
        
        self._service = None
        self._creds = None

    @classmethod
    def scopes_for(cls, write_access: bool = False) -> List[str]:
        scopes = list(cls.READ_SCOPES)
        if write_access:
            scopes.extend(cls.WRITE_SCOPES)
        return scopes

    def _resolve_scopes_from_env(self) -> List[str]:
        raw = str(os.environ.get("CHINTU_GOOGLE_CALENDAR_SCOPES", "") or "").strip()
        if raw:
            scopes = [x.strip() for x in raw.split(",") if x.strip()]
            if scopes:
                return scopes
        write_access = str(os.environ.get("CHINTU_GOOGLE_CALENDAR_WRITE_ACCESS", "") or "").strip().lower()
        return self.scopes_for(write_access in {"1", "true", "yes", "on"})

    def set_scopes(self, scopes: List[str]) -> None:
        self.scopes = [str(x).strip() for x in scopes if str(x).strip()] or self.scopes_for(False)
        self._service = None
        self._creds = None
        
    def save_credentials(self, json_content: str) -> bool:
        """Save provided JSON credentials string to file."""
        try:
            import json
            # Validate JSON
            data = json.loads(json_content)
            
            # Ensure directory exists
            os.makedirs(os.path.dirname(self.credentials_path), exist_ok=True)
            
            with open(self.credentials_path, 'w') as f:
                f.write(json_content)
            
            return True
        except Exception as e:
            logger.error(f"Failed to save credentials: {e}")
            return False
        
    @property
    def is_configured(self) -> bool:
        """Check if credentials are available."""
        return HAS_GOOGLE_API and os.path.exists(self.credentials_path)
    
    @property
    def is_authenticated(self) -> bool:
        """Check if we have valid credentials."""
        if not self._creds:
            self._load_credentials()
        return self._creds is not None and self._creds.valid
    
    def _load_credentials(self):
        """Load or refresh OAuth credentials."""
        if not HAS_GOOGLE_API:
            return
            
        if os.path.exists(self.token_path):
            self._creds = Credentials.from_authorized_user_file(self.token_path, self.scopes)
        else:
            # Phase 20: fallback to identity vault token if local token file is missing.
            try:
                from chintu_backend.security.identity_vault import get_identity_vault

                vault = get_identity_vault()
                token_json = vault.get_secret("google_calendar", "oauth_token")
                if token_json:
                    info = json.loads(token_json)
                    self._creds = Credentials.from_authorized_user_info(info, self.scopes)
                    if self._creds:
                        os.makedirs(os.path.dirname(self.token_path), exist_ok=True)
                        with open(self.token_path, "w", encoding="utf-8") as f:
                            f.write(self._creds.to_json())
            except Exception as e:
                logger.debug("Vault token restore skipped: %s", e)
            
        # Refresh if expired
        if self._creds and self._creds.expired and self._creds.refresh_token:
            try:
                self._creds.refresh(Request())
                self._persist_token()
            except Exception as e:
                logger.warning(f"Token refresh failed: {e}")
                self._creds = None
    
    def authenticate(self) -> bool:
        """
        Authenticate with Google (opens browser).
        
        Returns:
            True if successful
        """
        if not HAS_GOOGLE_API:
            logger.error("Google API libraries not installed")
            return False
            
        if not os.path.exists(self.credentials_path):
            logger.error(f"Credentials file not found: {self.credentials_path}")
            return False
        
        try:
            flow = InstalledAppFlow.from_client_secrets_file(
                self.credentials_path, self.scopes
            )
            self._creds = flow.run_local_server(port=0)
            
            self._persist_token()
                
            logger.info("Calendar authentication successful")
            return True
            
        except Exception as e:
            logger.error(f"Authentication failed: {e}")
            return False

    def _persist_token(self) -> None:
        if not self._creds:
            return
        token_json = self._creds.to_json()
        os.makedirs(os.path.dirname(self.token_path), exist_ok=True)
        with open(self.token_path, 'w', encoding="utf-8") as f:
            f.write(token_json)
        # Best-effort secure backup in vault (Phase 20).
        try:
            from chintu_backend.security.identity_vault import get_identity_vault

            vault = get_identity_vault()
            if vault.available:
                vault.store_secret(
                    service="google_calendar",
                    username="oauth_token",
                    secret=token_json,
                    note="OAuth token backup for Google Calendar integration.",
                    tags=["oauth", "google_calendar"],
                )
        except Exception:
            pass
    
    def _get_service(self):
        """Get or create calendar service."""
        if self._service:
            return self._service
            
        if not self.is_authenticated:
            raise RuntimeError("Not authenticated. Call authenticate() first.")
            
        self._service = build('calendar', 'v3', credentials=self._creds)
        return self._service
    
    def get_upcoming_events(self, max_results: int = 10, days_ahead: int = 7) -> List[Dict[str, Any]]:
        """
        Get upcoming calendar events.
        
        Args:
            max_results: Maximum number of events
            days_ahead: How many days ahead to look
            
        Returns:
            List of event dictionaries
        """
        if not self.is_authenticated:
            raise RuntimeError("Not authenticated")
            
        service = self._get_service()
        
        now = datetime.datetime.utcnow()
        time_min = now.isoformat() + 'Z'
        time_max = (now + datetime.timedelta(days=days_ahead)).isoformat() + 'Z'
        
        try:
            events_result = service.events().list(
                calendarId='primary',
                timeMin=time_min,
                timeMax=time_max,
                maxResults=max_results,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            
            # Format events
            formatted = []
            for event in events:
                start = event['start'].get('dateTime', event['start'].get('date'))
                
                formatted.append({
                    'id': event['id'],
                    'title': event.get('summary', 'No title'),
                    'start': start,
                    'end': event['end'].get('dateTime', event['end'].get('date')),
                    'location': event.get('location', ''),
                    'description': event.get('description', ''),
                })
            
            return formatted
            
        except Exception as e:
            logger.error(f"Failed to get events: {e}")
            return []
    
    def get_todays_events(self) -> List[Dict[str, Any]]:
        """Get today's events."""
        return self.get_upcoming_events(max_results=20, days_ahead=1)
    
    def get_next_event(self) -> Optional[Dict[str, Any]]:
        """Get the next upcoming event."""
        events = self.get_upcoming_events(max_results=1, days_ahead=7)
        return events[0] if events else None
    
    def create_event(
        self,
        title: str,
        start: datetime.datetime,
        end: Optional[datetime.datetime] = None,
        description: str = "",
        location: str = ""
    ) -> Optional[Dict[str, Any]]:
        """
        Create a new calendar event.
        
        Args:
            title: Event title
            start: Start time
            end: End time (default: 1 hour after start)
            description: Event description
            location: Event location
            
        Returns:
            Created event or None
        """
        if not self.is_authenticated:
            raise RuntimeError("Not authenticated")
            
        service = self._get_service()
        
        if end is None:
            end = start + datetime.timedelta(hours=1)
        
        event = {
            'summary': title,
            'location': location,
            'description': description,
            'start': {
                'dateTime': start.isoformat(),
                'timeZone': 'America/New_York',  # TODO: Make configurable
            },
            'end': {
                'dateTime': end.isoformat(),
                'timeZone': 'America/New_York',
            },
        }
        
        try:
            created = service.events().insert(
                calendarId='primary',
                body=event
            ).execute()
            
            logger.info(f"Created event: {title}")
            return {
                'id': created['id'],
                'title': title,
                'start': start.isoformat(),
                'end': end.isoformat(),
                'link': created.get('htmlLink'),
            }
            
        except Exception as e:
            logger.error(f"Failed to create event: {e}")
            return None
    
    def format_events_for_voice(self, events: List[Dict], include_details: bool = False) -> str:
        """Format events for TTS output."""
        if not events:
            return "You have no upcoming events."
            
        if len(events) == 1:
            e = events[0]
            return f"Your next event is {e['title']} at {self._format_time(e['start'])}."
        
        lines = [f"You have {len(events)} upcoming events:"]
        for i, e in enumerate(events[:5], 1):
            line = f"{i}. {e['title']} at {self._format_time(e['start'])}"
            if include_details and e.get('location'):
                line += f" at {e['location']}"
            lines.append(line)
            
        return "\n".join(lines)
    
    def _format_time(self, iso_time: str) -> str:
        """Format ISO time for speech."""
        try:
            dt = datetime.datetime.fromisoformat(iso_time.replace('Z', '+00:00'))
            return dt.strftime("%I:%M %p on %A")
        except:
            return iso_time


# Global instance
_calendar: Optional[GoogleCalendar] = None


def get_calendar() -> GoogleCalendar:
    """Get or create the global calendar instance."""
    global _calendar
    if _calendar is None:
        _calendar = GoogleCalendar()
    return _calendar
