"""
Content Agent - Social Media, Video Generation, and Content Pipelines.

Handles:
- YouTube video creation and scheduling
- Instagram/TikTok content automation
- AI-generated content (text, images, video)
- Multi-platform posting with approval gates
- Daily content based on learning/insights
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, time
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from enum import Enum

from chintu_backend.brain.swarm.base_agent import BaseAgent, AgentState
from chintu_backend.swarm.agent_runtime import create_agent_runtime
from chintu_backend.core.config import get_config
from chintu_backend.core.events import get_event_bus, Event, EventType

logger = logging.getLogger(__name__)


class Platform(Enum):
    YOUTUBE = "youtube"
    INSTAGRAM = "instagram"
    TIKTOK = "tiktok"
    TWITTER = "twitter"
    LINKEDIN = "linkedin"


class ContentType(Enum):
    VIDEO = "video"
    IMAGE = "image"
    TEXT = "text"
    CAROUSEL = "carousel"  # Multi-image
    REEL = "reel"  # Short video
    STORY = "story"


class ContentStatus(Enum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    SCHEDULED = "scheduled"
    POSTED = "posted"
    FAILED = "failed"


@dataclass
class ContentPiece:
    """A piece of content to be posted."""
    id: str
    title: str
    description: str
    content_type: ContentType
    platforms: List[Platform]
    status: ContentStatus = ContentStatus.DRAFT
    
    # Content data
    text: str = ""
    media_paths: List[str] = field(default_factory=list)
    thumbnail_path: Optional[str] = None
    
    # Scheduling
    scheduled_time: Optional[datetime] = None
    posted_at: Optional[datetime] = None
    
    # Platform-specific data
    youtube_data: Dict[str, Any] = field(default_factory=dict)
    instagram_data: Dict[str, Any] = field(default_factory=dict)
    
    # Analytics
    views: int = 0
    likes: int = 0
    comments: int = 0
    
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class ContentPipeline:
    """A recurring content pipeline."""
    id: str
    name: str
    description: str
    platforms: List[Platform]
    content_type: ContentType
    schedule: str  # "daily", "weekly", "every 2 days", etc.
    
    # Content generation
    topic: str  # e.g., "what I learned today"
    style: str  # e.g., "educational", "entertaining", "professional"
    
    # Settings
    auto_generate: bool = True
    require_approval: bool = True
    active: bool = True
    
    # Tracking
    last_posted: Optional[datetime] = None
    total_posts: int = 0
    
    created_at: datetime = field(default_factory=datetime.now)


class ContentAgent(BaseAgent):
    """
    Content creation and social media automation agent.
    
    Capabilities:
    - Create content pipelines (daily/weekly posting)
    - Generate AI content (text, images, video scripts)
    - Post to YouTube, Instagram, TikTok, etc.
    - Preview and approval workflow
    - Analytics tracking
    """
    
    def __init__(self):
        super().__init__(
            name="Content",
            description="Content creator - videos, posts, social media automation"
        )
        try:
            runtime = create_agent_runtime("content")
            self.attach_runtime(runtime)
        except Exception:
            pass
        
        self.config = get_config()
        self.event_bus = get_event_bus()
        
        self.content_dir = self.config.data_dir / "content"
        self.content_dir.mkdir(parents=True, exist_ok=True)
        
        self.content: Dict[str, ContentPiece] = {}
        self.pipelines: Dict[str, ContentPipeline] = {}
        self.pending_approval: Dict[str, ContentPiece] = {}
        
        self._load_data()
    
    def run(self, goal: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute content task based on goal."""
        self.update_state(AgentState.EXECUTING)
        self.log_step("Starting", f"Goal: {goal}")
        
        goal_lower = goal.lower()
        context = context or {}
        
        # Detect intent
        if any(kw in goal_lower for kw in ["pipeline", "daily", "weekly", "schedule", "recurring"]):
            return self._handle_create_pipeline(goal, context)
        elif any(kw in goal_lower for kw in ["post", "upload", "publish"]):
            return self._handle_post(goal, context)
        elif any(kw in goal_lower for kw in ["generate", "create", "make"]):
            return self._handle_generate_content(goal, context)
        elif any(kw in goal_lower for kw in ["approve", "review"]):
            return self._handle_approval(goal, context)
        else:
            # Ask clarifying questions
            return self._ask_clarification(goal, context)
    
    def _handle_create_pipeline(self, goal: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Create a content pipeline."""
        self.log_step("Pipeline", "Gathering requirements for content pipeline")
        
        # Extract information from goal
        platforms = self._detect_platforms(goal)
        frequency = self._detect_frequency(goal)
        content_type = self._detect_content_type(goal)
        
        # Generate clarifying questions
        questions = []
        
        if not platforms:
            questions.append("Which platforms? (YouTube, Instagram, TikTok, Twitter, LinkedIn)")
        
        if "learn" in goal.lower() or "daily" in goal.lower():
            topic = "daily learnings and insights"
        else:
            questions.append("What topic/theme should the content be about?")
            topic = context.get("topic", "")
        
        questions.append("What style? (educational, entertaining, professional, casual)")
        questions.append("Should each post require your approval before publishing?")
        questions.append("What time of day should posts go out?")
        
        # If we have questions, ask them
        if questions and not context.get("answers_provided"):
            return {
                "success": True,
                "requires_input": True,
                "type": "pipeline_setup",
                "questions": questions,
                "detected": {
                    "platforms": [p.value for p in platforms],
                    "frequency": frequency,
                    "content_type": content_type.value if content_type else None,
                    "topic": topic
                },
                "message": self._format_pipeline_questions(questions, platforms, frequency)
            }
        
        # Create the pipeline
        import uuid
        pipeline_id = str(uuid.uuid4())[:8]
        
        pipeline = ContentPipeline(
            id=pipeline_id,
            name=context.get("name", f"{topic[:30]} Pipeline"),
            description=goal,
            platforms=platforms or [Platform.YOUTUBE, Platform.INSTAGRAM],
            content_type=content_type or ContentType.VIDEO,
            schedule=frequency or "daily",
            topic=topic or context.get("topic", "tech insights"),
            style=context.get("style", "educational"),
            require_approval=context.get("require_approval", True)
        )
        
        self.pipelines[pipeline_id] = pipeline
        self._save_pipeline(pipeline)
        
        return {
            "success": True,
            "pipeline_id": pipeline_id,
            "pipeline": {
                "name": pipeline.name,
                "platforms": [p.value for p in pipeline.platforms],
                "schedule": pipeline.schedule,
                "topic": pipeline.topic,
                "require_approval": pipeline.require_approval
            },
            "message": f"✅ Created pipeline: **{pipeline.name}**\n\n" +
                      f"📅 Schedule: {pipeline.schedule}\n" +
                      f"📱 Platforms: {', '.join(p.value for p in pipeline.platforms)}\n" +
                      f"🎯 Topic: {pipeline.topic}\n" +
                      f"✓ Approval required: {pipeline.require_approval}\n\n" +
                      "I'll generate content and ask for your approval before posting."
        }
    
    def _handle_generate_content(self, goal: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Generate content (text, script, video idea)."""
        self.log_step("Generate", f"Creating content for: {goal}")
        
        platforms = self._detect_platforms(goal)
        content_type = self._detect_content_type(goal)
        
        # Generate content using LLM
        content_data = self._generate_content_with_llm(goal, content_type, platforms)
        
        import uuid
        content_id = str(uuid.uuid4())[:8]
        
        content = ContentPiece(
            id=content_id,
            title=content_data.get("title", "Generated Content"),
            description=content_data.get("description", ""),
            content_type=content_type or ContentType.VIDEO,
            platforms=platforms or [Platform.YOUTUBE],
            status=ContentStatus.PENDING_APPROVAL,
            text=content_data.get("script", content_data.get("text", ""))
        )
        
        self.content[content_id] = content
        self.pending_approval[content_id] = content
        
        return {
            "success": True,
            "content_id": content_id,
            "requires_approval": True,
            "type": "content_approval",
            "content": {
                "title": content.title,
                "description": content.description,
                "type": content.content_type.value,
                "platforms": [p.value for p in content.platforms],
                "script": content.text[:500] + ("..." if len(content.text) > 500 else "")
            },
            "message": self._format_content_preview(content)
        }
    
    def _handle_post(self, goal: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Handle direct posting request."""
        content_id = context.get("content_id")
        
        if content_id:
            content = self.content.get(content_id)
            if not content:
                return {"success": False, "error": "Content not found"}
            
            if content.status != ContentStatus.APPROVED:
                return {
                    "success": False,
                    "requires_approval": True,
                    "message": "This content needs approval before posting."
                }
            
            return self._execute_post(content)
        
        # No content ID - generate new content first
        return self._handle_generate_content(goal, context)
    
    def _handle_approval(self, goal: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Handle approval requests."""
        if not self.pending_approval:
            return {"success": True, "message": "No content pending approval."}
        
        return {
            "success": True,
            "pending": [
                {
                    "id": c.id,
                    "title": c.title,
                    "type": c.content_type.value,
                    "platforms": [p.value for p in c.platforms]
                }
                for c in self.pending_approval.values()
            ]
        }
    
    def approve_content(self, content_id: str) -> Dict[str, Any]:
        """Approve content for posting."""
        content = self.content.get(content_id)
        if not content:
            return {"success": False, "error": "Content not found"}
        
        content.status = ContentStatus.APPROVED
        self.pending_approval.pop(content_id, None)
        
        return {
            "success": True,
            "message": f"Approved: {content.title}",
            "ready_to_post": True
        }
    
    def schedule_content(self, content_id: str, scheduled_time: datetime) -> Dict[str, Any]:
        """Schedule content for future posting."""
        content = self.content.get(content_id)
        if not content:
            return {"success": False, "error": "Content not found"}
        
        content.scheduled_time = scheduled_time
        content.status = ContentStatus.SCHEDULED
        
        return {
            "success": True,
            "message": f"Scheduled '{content.title}' for {scheduled_time.strftime('%Y-%m-%d %H:%M')}"
        }
    
    def _ask_clarification(self, goal: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Ask clarifying questions before proceeding."""
        questions = [
            "What type of content? (video, image, text post)",
            "Which platforms? (YouTube, Instagram, TikTok, Twitter, LinkedIn)",
            "Is this a one-time post or recurring pipeline?",
            "What's the main topic or theme?",
        ]
        
        return {
            "success": True,
            "requires_input": True,
            "type": "clarification",
            "questions": questions,
            "message": "I'd love to help with your content! Let me understand better:\n\n" +
                      "\n".join(f"{i+1}. {q}" for i, q in enumerate(questions))
        }
    
    def _detect_platforms(self, text: str) -> List[Platform]:
        """Detect platforms from text."""
        text_lower = text.lower()
        platforms = []
        
        if "youtube" in text_lower:
            platforms.append(Platform.YOUTUBE)
        if "instagram" in text_lower or "insta" in text_lower:
            platforms.append(Platform.INSTAGRAM)
        if "tiktok" in text_lower:
            platforms.append(Platform.TIKTOK)
        if "twitter" in text_lower or "x" in text_lower:
            platforms.append(Platform.TWITTER)
        if "linkedin" in text_lower:
            platforms.append(Platform.LINKEDIN)
        
        return platforms
    
    def _detect_frequency(self, text: str) -> str:
        """Detect posting frequency from text."""
        text_lower = text.lower()
        
        if "daily" in text_lower:
            return "daily"
        elif "weekly" in text_lower:
            return "weekly"
        elif "every 2 days" in text_lower or "every two days" in text_lower:
            return "every 2 days"
        elif "every 3 days" in text_lower or "every three days" in text_lower:
            return "every 3 days"
        elif "hourly" in text_lower:
            return "hourly"
        
        return "daily"
    
    def _detect_content_type(self, text: str) -> Optional[ContentType]:
        """Detect content type from text."""
        text_lower = text.lower()
        
        if "video" in text_lower:
            return ContentType.VIDEO
        elif "reel" in text_lower or "short" in text_lower:
            return ContentType.REEL
        elif "image" in text_lower or "photo" in text_lower:
            return ContentType.IMAGE
        elif "carousel" in text_lower:
            return ContentType.CAROUSEL
        elif "story" in text_lower:
            return ContentType.STORY
        elif "text" in text_lower or "post" in text_lower:
            return ContentType.TEXT
        
        return None
    
    def _generate_content_with_llm(
        self, 
        goal: str, 
        content_type: ContentType,
        platforms: List[Platform]
    ) -> Dict[str, Any]:
        """Generate content using LLM."""
        try:
            from chintu_backend.brain.llm.ollama_client import OllamaClient
            
            llm = OllamaClient(
                host=getattr(self.config, 'ollama_host', 'http://localhost:11434'),
                model=getattr(self.config, 'ollama_model', 'qwen2.5:3b')
            )
            
            type_str = content_type.value if content_type else "video"
            platforms_str = ", ".join(p.value for p in platforms) if platforms else "YouTube"
            
            prompt = f"""Create {type_str} content for {platforms_str}.

Request: {goal}

Generate:
1. Catchy title
2. Description/caption
3. Script or content text
4. Hashtags (if applicable)

Format as JSON:
{{
    "title": "...",
    "description": "...",
    "script": "...",
    "hashtags": ["...", "..."],
    "thumbnail_idea": "..."
}}"""
            
            response = llm.generate(prompt) if hasattr(llm, 'generate') else llm.chat(prompt)
            
            # Parse JSON
            try:
                if "```json" in response:
                    json_str = response.split("```json")[1].split("```")[0]
                elif "```" in response:
                    json_str = response.split("```")[1].split("```")[0]
                else:
                    start = response.find("{")
                    end = response.rfind("}") + 1
                    json_str = response[start:end]
                
                return json.loads(json_str)
            except:
                return {
                    "title": "Generated Content",
                    "description": goal,
                    "script": response,
                    "text": response
                }
                
        except Exception as e:
            logger.error(f"Content generation failed: {e}")
            return {
                "title": "Content Draft",
                "description": goal,
                "script": f"[Script draft for: {goal}]",
                "text": goal
            }
    
    def _format_pipeline_questions(
        self, 
        questions: List[str],
        platforms: List[Platform],
        frequency: str
    ) -> str:
        """Format pipeline setup questions."""
        msg = "📋 **Setting up your content pipeline**\n\n"
        
        if platforms:
            msg += f"✓ Detected platforms: {', '.join(p.value for p in platforms)}\n"
        if frequency:
            msg += f"✓ Detected schedule: {frequency}\n"
        
        msg += "\nI have a few questions:\n\n"
        for i, q in enumerate(questions, 1):
            msg += f"{i}. {q}\n"
        
        return msg
    
    def _format_content_preview(self, content: ContentPiece) -> str:
        """Format content preview for approval."""
        msg = f"📝 **Content Ready for Review**\n\n"
        msg += f"**Title:** {content.title}\n\n"
        msg += f"**Description:** {content.description}\n\n"
        msg += f"**Type:** {content.content_type.value}\n"
        msg += f"**Platforms:** {', '.join(p.value for p in content.platforms)}\n\n"
        
        if content.text:
            preview = content.text[:500]
            if len(content.text) > 500:
                preview += "..."
            msg += f"**Script/Text:**\n```\n{preview}\n```\n\n"
        
        msg += "Reply 'approve' to proceed, or give feedback to modify."
        return msg
    
    def _execute_post(self, content: ContentPiece) -> Dict[str, Any]:
        """Execute posting to platforms."""
        results = {}
        
        for platform in content.platforms:
            try:
                if platform == Platform.YOUTUBE:
                    result = self._post_youtube(content)
                elif platform == Platform.INSTAGRAM:
                    result = self._post_instagram(content)
                elif platform == Platform.TIKTOK:
                    result = self._post_tiktok(content)
                elif platform == Platform.TWITTER:
                    result = self._post_twitter(content)
                else:
                    result = {"success": False, "error": "Platform not implemented"}
                
                results[platform.value] = result
                
            except Exception as e:
                results[platform.value] = {"success": False, "error": str(e)}
        
        content.status = ContentStatus.POSTED
        content.posted_at = datetime.now()
        
        return {
            "success": all(r.get("success") for r in results.values()),
            "results": results
        }
    
    def _post_youtube(self, content: ContentPiece) -> Dict[str, Any]:
        """Post to YouTube (requires YouTube API credentials)."""
        # Check for YouTube credentials
        youtube_key = os.environ.get("YOUTUBE_API_KEY")
        if not youtube_key:
            return {
                "success": False,
                "error": "YouTube API key not configured",
                "requires": ["YOUTUBE_API_KEY"]
            }
        
        # In practice, would use YouTube Data API
        logger.info(f"Would post to YouTube: {content.title}")
        return {
            "success": True,
            "message": "Posted to YouTube (simulated)",
            "url": f"https://youtube.com/watch?v=example"
        }
    
    def _post_instagram(self, content: ContentPiece) -> Dict[str, Any]:
        """Post to Instagram (requires Instagram Graph API)."""
        instagram_token = os.environ.get("INSTAGRAM_ACCESS_TOKEN")
        if not instagram_token:
            return {
                "success": False,
                "error": "Instagram access token not configured",
                "requires": ["INSTAGRAM_ACCESS_TOKEN"]
            }
        
        logger.info(f"Would post to Instagram: {content.title}")
        return {
            "success": True,
            "message": "Posted to Instagram (simulated)",
            "url": "https://instagram.com/p/example"
        }
    
    def _post_tiktok(self, content: ContentPiece) -> Dict[str, Any]:
        """Post to TikTok."""
        logger.info(f"Would post to TikTok: {content.title}")
        return {
            "success": True,
            "message": "Posted to TikTok (simulated)"
        }
    
    def _post_twitter(self, content: ContentPiece) -> Dict[str, Any]:
        """Post to Twitter/X."""
        twitter_key = os.environ.get("TWITTER_API_KEY")
        if not twitter_key:
            return {
                "success": False,
                "error": "Twitter API key not configured",
                "requires": ["TWITTER_API_KEY"]
            }
        
        logger.info(f"Would post to Twitter: {content.title}")
        return {
            "success": True,
            "message": "Posted to Twitter (simulated)"
        }
    
    async def run_daily_content(self):
        """Run daily content generation for active pipelines."""
        for pipeline in self.pipelines.values():
            if not pipeline.active:
                continue
            
            if pipeline.schedule == "daily":
                # Check if already posted today
                if pipeline.last_posted:
                    if pipeline.last_posted.date() == datetime.now().date():
                        continue
                
                # Generate content
                content = await self._generate_pipeline_content(pipeline)
                
                if pipeline.require_approval:
                    # Queue for approval
                    self.pending_approval[content.id] = content
                    
                    # Notify user
                    try:
                        await self.event_bus.publish(Event(
                            type=EventType.CONTENT_READY,
                            data={
                                "content_id": content.id,
                                "title": content.title,
                                "pipeline": pipeline.name,
                                "requires_approval": True
                            }
                        ))
                    except Exception:
                        pass
                else:
                    # Auto-post
                    self._execute_post(content)
                    pipeline.last_posted = datetime.now()
                    pipeline.total_posts += 1
    
    async def _generate_pipeline_content(self, pipeline: ContentPipeline) -> ContentPiece:
        """Generate content for a pipeline."""
        # Get today's learnings from memory if topic is about daily learnings
        learnings = ""
        if "learn" in pipeline.topic.lower():
            try:
                from chintu_backend.brain.swarm.skill_promotion import get_learning_scheduler
                scheduler = get_learning_scheduler()
                completed = scheduler.get_completed_tasks(limit=5)
                learnings = "\n".join(t.description for t in completed)
            except Exception:
                learnings = "Today I explored new AI techniques and automation strategies."
        
        goal = f"Create {pipeline.content_type.value} about {pipeline.topic}. " + \
               f"Style: {pipeline.style}. " + \
               (f"Today's learnings: {learnings}" if learnings else "")
        
        content_data = self._generate_content_with_llm(
            goal, 
            pipeline.content_type,
            pipeline.platforms
        )
        
        import uuid
        content_id = str(uuid.uuid4())[:8]
        
        content = ContentPiece(
            id=content_id,
            title=content_data.get("title", f"Daily {pipeline.topic}"),
            description=content_data.get("description", ""),
            content_type=pipeline.content_type,
            platforms=pipeline.platforms,
            status=ContentStatus.PENDING_APPROVAL,
            text=content_data.get("script", content_data.get("text", ""))
        )
        
        self.content[content_id] = content
        return content
    
    def _load_data(self):
        """Load content and pipelines from disk."""
        # Load pipelines
        pipelines_file = self.content_dir / "pipelines.json"
        if pipelines_file.exists():
            try:
                data = json.loads(pipelines_file.read_text())
                for p in data:
                    pipeline = ContentPipeline(
                        id=p["id"],
                        name=p["name"],
                        description=p["description"],
                        platforms=[Platform(x) for x in p["platforms"]],
                        content_type=ContentType(p["content_type"]),
                        schedule=p["schedule"],
                        topic=p["topic"],
                        style=p.get("style", "educational"),
                        require_approval=p.get("require_approval", True),
                        active=p.get("active", True),
                        total_posts=p.get("total_posts", 0)
                    )
                    self.pipelines[pipeline.id] = pipeline
            except Exception as e:
                logger.warning(f"Could not load pipelines: {e}")
    
    def _save_pipeline(self, pipeline: ContentPipeline):
        """Save pipeline to disk."""
        pipelines_file = self.content_dir / "pipelines.json"
        
        # Load existing
        existing = []
        if pipelines_file.exists():
            try:
                existing = json.loads(pipelines_file.read_text())
                existing = [p for p in existing if p["id"] != pipeline.id]
            except Exception:
                pass
        
        # Add/update
        existing.append({
            "id": pipeline.id,
            "name": pipeline.name,
            "description": pipeline.description,
            "platforms": [p.value for p in pipeline.platforms],
            "content_type": pipeline.content_type.value,
            "schedule": pipeline.schedule,
            "topic": pipeline.topic,
            "style": pipeline.style,
            "require_approval": pipeline.require_approval,
            "active": pipeline.active,
            "total_posts": pipeline.total_posts,
            "created_at": pipeline.created_at.isoformat()
        })
        
        pipelines_file.write_text(json.dumps(existing, indent=2))
    
    def stop(self):
        """Stop the agent."""
        self.update_state(AgentState.IDLE)


# Singleton instance
_content_agent: Optional[ContentAgent] = None


def get_content_agent() -> ContentAgent:
    """Get or create the content agent singleton."""
    global _content_agent
    if _content_agent is None:
        _content_agent = ContentAgent()
    return _content_agent
