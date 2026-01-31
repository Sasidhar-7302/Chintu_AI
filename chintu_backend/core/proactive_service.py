"""
Proactive Service for Chintu AI Assistant.

Runs background checks and notifies user of important events:
- Upcoming meetings (calendar)
- Unread important emails
- Task reminders
- Time-based suggestions

Follows tool-first architecture: polling APIs, no LLM needed for detection.
"""

import logging
import asyncio
import datetime
from typing import Optional, Callable, List, Dict, Any
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class NotificationType(Enum):
    """Types of proactive notifications."""
    CALENDAR_REMINDER = "calendar"
    EMAIL_ALERT = "email"
    TASK_DUE = "task"
    SUGGESTION = "suggestion"


@dataclass
class Notification:
    """A proactive notification."""
    type: NotificationType
    title: str
    message: str
    priority: int = 5  # 1-10, higher = more urgent
    data: Dict[str, Any] = None


class PatternLearner:
    """Learns user app usage patterns."""
    
    def __init__(self, db_path: str = None):
        import sqlite3
        from pathlib import Path
        
        if db_path is None:
            db_path = Path.home() / ".chintu" / "patterns.db"
            
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        
    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS app_usage (
                app_name TEXT,
                hour INTEGER,
                day_of_week INTEGER,
                count INTEGER,
                PRIMARY KEY (app_name, hour, day_of_week)
            )
        """)
        conn.commit()
        conn.close()
        
    def record_usage(self, app_name: str):
        """Record an app being open."""
        now = datetime.datetime.now()
        hour = now.hour
        day = now.weekday()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO app_usage (app_name, hour, day_of_week, count)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(app_name, hour, day_of_week) 
            DO UPDATE SET count = count + 1
        """, (app_name, hour, day))
        conn.commit()
        conn.close()
        
    def get_suggestions(self, min_confidence: int = 5) -> List[str]:
        """Get apps suggested for right now."""
        now = datetime.datetime.now()
        hour = now.hour
        day = now.weekday()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT app_name FROM app_usage 
            WHERE hour = ? AND day_of_week = ? AND count >= ?
            ORDER BY count DESC
        """, (hour, day, min_confidence))
        
        apps = [row[0] for row in cursor.fetchall()]
        conn.close()
        return apps


class ProactiveService:
    """
    Background service for proactive intelligence.
    
    Runs periodic checks and triggers notifications:
    - Every 5 min: Check calendar for upcoming meetings
    - Every 15 min: Check unread emails (if configured)
    - Every hour: Suggest tasks/reminders
    """
    
    def __init__(
        self,
        speak_callback: Optional[Callable[[str], None]] = None,
        notify_callback: Optional[Callable[[Notification], None]] = None,
    ):
        """
        Initialize proactive service.
        
        Args:
            speak_callback: Function to speak notifications
            notify_callback: Function to send UI notifications
        """
        self.speak = speak_callback
        self.notify = notify_callback
        
        self._running = False
        self._task: Optional[asyncio.Task] = None
        
        # Check intervals (seconds)
        self.calendar_interval = 5 * 60  # 5 minutes
        self.email_interval = 15 * 60   # 15 minutes
        self.suggestion_interval = 60 * 60  # 1 hour
        
        # Last check times
        self._last_calendar_check = 0
        self._last_email_check = 0
        self._last_suggestion = 0
        
        # Notification cooldowns (avoid repeating same notification)
        self._notified_events: Dict[str, float] = {}
        
        # Pattern Learner
        self.learner = PatternLearner()
        
    async def start(self):
        """Start the proactive service."""
        if self._running:
            return
            
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Proactive service started")
        
    async def stop(self):
        """Stop the proactive service."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Proactive service stopped")
        
    async def _run_loop(self):
        """Main background loop."""
        while self._running:
            try:
                now = datetime.datetime.now().timestamp()
                
                # Calendar check
                if now - self._last_calendar_check >= self.calendar_interval:
                    await self._check_calendar()
                    self._last_calendar_check = now
                
                # Email check (if configured)
                if now - self._last_email_check >= self.email_interval:
                    await self._check_email()
                    self._last_email_check = now
                
                # Hourly suggestions
                if now - self._last_suggestion >= self.suggestion_interval:
                    await self._make_suggestions()
                    self._last_suggestion = now
                
                # Sleep between cycles
                await asyncio.sleep(60)  # Check every minute
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Proactive service error: {e}")
                await asyncio.sleep(60)
    
    async def _check_calendar(self):
        """Check for upcoming calendar events."""
        try:
            from ..integrations.google_calendar import get_calendar
            
            calendar = get_calendar()
            if not calendar.is_authenticated:
                return
            
            events = calendar.get_upcoming_events(max_results=5, days_ahead=1)
            
            # While checking calendar, also record current open apps for learning
            try:
                from ..automation.platform.window_manager import get_window_manager
                summary = get_window_manager().get_window_summary()
                # Extract simple app names (this is a naive parse, ideally window_manager returns structured list)
                # For now, just recording "active" status if we had a proper module.
                # In v5.3, we'd iterate running processes here.
                pass 
            except Exception:
                pass
            
            for event in events:
                event_id = event['id']
                start_str = event['start']
                title = event['title']
                
                # Parse start time
                try:
                    start = datetime.datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                except:
                    continue
                
                # Calculate time until event
                now = datetime.datetime.now(start.tzinfo)
                delta = start - now
                minutes_until = delta.total_seconds() / 60
                
                # Notify at 10 minutes before
                if 5 <= minutes_until <= 15:
                    # Check cooldown (don't notify twice for same event)
                    if event_id in self._notified_events:
                        continue
                    
                    message = f"You have {title} in about {int(minutes_until)} minutes."
                    
                    if self.speak:
                        self.speak(message)
                    
                    if self.notify:
                        self.notify(Notification(
                            type=NotificationType.CALENDAR_REMINDER,
                            title="Upcoming Meeting",
                            message=message,
                            priority=8,
                            data=event
                        ))
                    
                    self._notified_events[event_id] = now.timestamp()
                    logger.info(f"Calendar notification: {title}")
                    
        except Exception as e:
            logger.debug(f"Calendar check skipped: {e}")
    
    async def _check_email(self):
        """Check for important unread emails."""
        # Gmail integration would go here
        # For now, this is a placeholder
        pass
    
    async def _make_suggestions(self):
        """Make time-based suggestions."""
        now = datetime.datetime.now()
        hour = now.hour
        
        # 1. Pattern-based App Suggestions
        suggested_apps = self.learner.get_suggestions()
        if suggested_apps:
             app_list = ", ".join(suggested_apps[:3])
             message = f"It's {hour}:00. Usually you use: {app_list}. Want me to open them?"
             
             # Notify only if not recently notified about this
             key = f"suggestion_{hour}_{app_list}"
             if key not in self._notified_events:
                 if self.notify:
                     self.notify(Notification(
                         type=NotificationType.SUGGESTION,
                         title="Routine Suggestion",
                         message=message,
                         priority=4
                     ))
                 self._notified_events[key] = now.timestamp()

        # Morning brief (8-9 AM)
        if 8 <= hour < 9:
            await self._morning_brief()
        
        # End of day (5-6 PM)
        elif 17 <= hour < 18:
            await self._evening_summary()
    
    async def _morning_brief(self):
        """Generate morning brief."""
        try:
            from ..integrations.google_calendar import get_calendar
            
            calendar = get_calendar()
            if not calendar.is_authenticated:
                return
            
            events = calendar.get_todays_events()
            
            if events and self.speak:
                brief = calendar.format_events_for_voice(events)
                self.speak(f"Good morning! {brief}")
                
        except Exception as e:
            logger.debug(f"Morning brief skipped: {e}")
    
    async def _evening_summary(self):
        """Generate evening summary."""
        # Placeholder for end-of-day summary
        pass
    
    def force_calendar_check(self):
        """Force an immediate calendar check."""
        self._last_calendar_check = 0


# Global instance
_service: Optional[ProactiveService] = None


def get_proactive_service() -> ProactiveService:
    """Get or create the global proactive service."""
    global _service
    if _service is None:
        _service = ProactiveService()
    return _service
