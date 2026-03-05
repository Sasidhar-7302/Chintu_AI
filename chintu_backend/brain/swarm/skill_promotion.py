"""
Skill Promotion - Convert completed tasks into reusable skills.

Features:
- Promote successful tasks to skills
- Export skills for fine-tuning
- Versioned skill recipes
- Daily learning hour scheduler (6-7 AM)
"""

import json
import logging
import hashlib
import asyncio
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, field
from enum import Enum
import threading

from chintu_backend.core.config import get_config
from chintu_backend.core.events import get_event_bus, Event, EventType

logger = logging.getLogger(__name__)


class SkillStatus(Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    DEPRECATED = "deprecated"


@dataclass
class SkillRecipe:
    """A reusable skill extracted from a completed task."""
    id: str
    name: str
    description: str
    trigger_phrases: List[str]  # What user might say to invoke this
    steps: List[Dict[str, Any]]  # Execution steps
    tools_required: List[str]
    estimated_time_minutes: int
    status: SkillStatus = SkillStatus.ACTIVE
    version: int = 1
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    success_count: int = 0
    failure_count: int = 0
    source_task_id: Optional[str] = None
    tags: List[str] = field(default_factory=list)


@dataclass
class LearningTask:
    """A task scheduled for the daily learning hour."""
    id: str
    type: str  # news, skill_review, upgrade_check, user_topic
    description: str
    source: str
    priority: int = 5  # 1-10
    scheduled_at: datetime = field(default_factory=datetime.now)
    completed: bool = False
    result: Optional[Dict[str, Any]] = None


class SkillPromoter:
    """
    Promotes completed tasks to reusable skills.
    """
    
    def __init__(self):
        self.config = get_config()
        self.skills_dir = self.config.data_dir / "skills"
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        
        self.skills: Dict[str, SkillRecipe] = {}
        self._load_skills()
    
    def promote_task(
        self,
        task_id: str,
        task_summary: Dict[str, Any],
        name: str,
        description: str = "",
        trigger_phrases: List[str] = None
    ) -> SkillRecipe:
        """
        Promote a completed task to a reusable skill.
        
        Args:
            task_id: ID of the source task
            task_summary: Summary of what the task did
            name: Human-readable skill name
            description: Skill description
            trigger_phrases: Phrases that should trigger this skill
            
        Returns:
            SkillRecipe for the new skill
        """
        import uuid
        skill_id = str(uuid.uuid4())[:8]
        
        # Extract steps from task summary
        steps = task_summary.get("steps", [])
        tools = task_summary.get("tools_used", [])
        time_minutes = task_summary.get("duration_minutes", 5)
        
        # Generate trigger phrases if not provided
        if not trigger_phrases:
            trigger_phrases = self._generate_trigger_phrases(name, description)
        
        skill = SkillRecipe(
            id=skill_id,
            name=name,
            description=description or task_summary.get("description", ""),
            trigger_phrases=trigger_phrases,
            steps=steps,
            tools_required=tools,
            estimated_time_minutes=time_minutes,
            source_task_id=task_id,
            tags=task_summary.get("tags", [])
        )
        
        self.skills[skill_id] = skill
        self._save_skill(skill)
        
        logger.info(f"Promoted task {task_id} to skill: {name}")
        return skill
    
    def get_skill(self, skill_id: str) -> Optional[SkillRecipe]:
        """Get skill by ID."""
        return self.skills.get(skill_id)
    
    def find_skill_by_trigger(self, user_input: str) -> Optional[SkillRecipe]:
        """Find a skill matching user input."""
        user_lower = user_input.lower()
        
        best_match = None
        best_score = 0
        
        for skill in self.skills.values():
            if skill.status != SkillStatus.ACTIVE:
                continue
            
            for phrase in skill.trigger_phrases:
                # Simple matching - count word overlap
                phrase_words = set(phrase.lower().split())
                input_words = set(user_lower.split())
                overlap = len(phrase_words & input_words)
                
                if overlap > best_score:
                    best_score = overlap
                    best_match = skill
        
        # Require at least 2 matching words
        return best_match if best_score >= 2 else None
    
    def list_skills(self, status: SkillStatus = None, tag: str = None) -> List[SkillRecipe]:
        """List skills with optional filtering."""
        skills = list(self.skills.values())
        
        if status:
            skills = [s for s in skills if s.status == status]
        
        if tag:
            skills = [s for s in skills if tag in s.tags]
        
        return sorted(skills, key=lambda s: s.success_count, reverse=True)
    
    def update_skill(self, skill_id: str, **updates) -> bool:
        """Update a skill."""
        skill = self.skills.get(skill_id)
        if not skill:
            return False
        
        for key, value in updates.items():
            if hasattr(skill, key):
                setattr(skill, key, value)
        
        skill.updated_at = datetime.now()
        skill.version += 1
        
        self._save_skill(skill)
        return True
    
    def record_execution(self, skill_id: str, success: bool):
        """Record skill execution result."""
        skill = self.skills.get(skill_id)
        if skill:
            if success:
                skill.success_count += 1
            else:
                skill.failure_count += 1
            self._save_skill(skill)
    
    def deprecate_skill(self, skill_id: str) -> bool:
        """Mark a skill as deprecated."""
        return self.update_skill(skill_id, status=SkillStatus.DEPRECATED)
    
    def export_for_training(self, output_path: Path = None) -> Path:
        """
        Export all active skills as training data for fine-tuning.
        
        Returns path to the exported JSONL file.
        """
        output_path = output_path or (self.config.data_dir / "training" / f"skills_{datetime.now().strftime('%Y%m%d')}.jsonl")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        training_data = []
        
        for skill in self.skills.values():
            if skill.status != SkillStatus.ACTIVE:
                continue
            
            # Create training examples from trigger phrases
            for phrase in skill.trigger_phrases:
                example = {
                    "messages": [
                        {"role": "user", "content": phrase},
                        {"role": "assistant", "content": f"I'll help you with that using the '{skill.name}' skill.\n\n" +
                         f"Steps:\n" + "\n".join(f"- {s.get('description', s)}" for s in skill.steps[:5])}
                    ],
                    "skill_id": skill.id,
                    "skill_name": skill.name
                }
                training_data.append(example)
        
        # Write JSONL
        with open(output_path, 'w') as f:
            for item in training_data:
                f.write(json.dumps(item) + "\n")
        
        logger.info(f"Exported {len(training_data)} training examples to {output_path}")
        return output_path
    
    def _generate_trigger_phrases(self, name: str, description: str) -> List[str]:
        """Generate trigger phrases from skill name and description."""
        phrases = [name.lower()]
        
        # Add variations
        words = name.lower().split()
        if len(words) > 1:
            phrases.append(" ".join(words))
            phrases.append(f"do {name.lower()}")
            phrases.append(f"run {name.lower()}")
        
        # From description
        if description:
            desc_words = description.lower().split()[:5]
            if len(desc_words) >= 3:
                phrases.append(" ".join(desc_words[:3]))
        
        return phrases
    
    def _load_skills(self):
        """Load skills from disk."""
        for skill_file in self.skills_dir.glob("*.json"):
            try:
                data = json.loads(skill_file.read_text())
                skill = SkillRecipe(
                    id=data["id"],
                    name=data["name"],
                    description=data["description"],
                    trigger_phrases=data["trigger_phrases"],
                    steps=data["steps"],
                    tools_required=data["tools_required"],
                    estimated_time_minutes=data["estimated_time_minutes"],
                    status=SkillStatus(data.get("status", "active")),
                    version=data.get("version", 1),
                    created_at=datetime.fromisoformat(data["created_at"]),
                    success_count=data.get("success_count", 0),
                    failure_count=data.get("failure_count", 0),
                    tags=data.get("tags", [])
                )
                self.skills[skill.id] = skill
            except Exception as e:
                logger.warning(f"Could not load skill {skill_file.name}: {e}")
    
    def _save_skill(self, skill: SkillRecipe):
        """Save skill to disk."""
        skill_file = self.skills_dir / f"{skill.id}.json"
        data = {
            "id": skill.id,
            "name": skill.name,
            "description": skill.description,
            "trigger_phrases": skill.trigger_phrases,
            "steps": skill.steps,
            "tools_required": skill.tools_required,
            "estimated_time_minutes": skill.estimated_time_minutes,
            "status": skill.status.value,
            "version": skill.version,
            "created_at": skill.created_at.isoformat(),
            "updated_at": skill.updated_at.isoformat(),
            "success_count": skill.success_count,
            "failure_count": skill.failure_count,
            "source_task_id": skill.source_task_id,
            "tags": skill.tags
        }
        skill_file.write_text(json.dumps(data, indent=2))


class DailyLearningScheduler:
    """
    Manages the daily learning hour (6-7 AM by default).
    
    During learning hour:
    - Collect news and updates
    - Review skill performance
    - Check for upgrade opportunities
    - Process user-requested learning topics
    """
    
    def __init__(
        self,
        learning_start: time = time(6, 0),  # 6:00 AM
        learning_end: time = time(7, 0),    # 7:00 AM
    ):
        self.config = get_config()
        self.event_bus = get_event_bus()
        
        self.learning_start = learning_start
        self.learning_end = learning_end
        
        self.queue_dir = self.config.data_dir / "learning_queue"
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        
        self.pending_tasks: Dict[str, LearningTask] = {}
        self.completed_tasks: List[LearningTask] = []
        
        self._running = False
        self._scheduler_thread: Optional[threading.Thread] = None
        
        self._load_queue()
    
    def start(self):
        """Start the learning scheduler."""
        if self._running:
            return
        
        self._running = True
        self._scheduler_thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self._scheduler_thread.start()
        logger.info(f"Learning scheduler started ({self.learning_start} - {self.learning_end})")
    
    def stop(self):
        """Stop the learning scheduler."""
        self._running = False
    
    def queue_learning(
        self,
        type: str,
        description: str,
        source: str = "user",
        priority: int = 5
    ) -> LearningTask:
        """
        Queue a topic for learning during the next learning hour.
        
        Args:
            type: Type of learning (news, skill_review, upgrade_check, user_topic)
            description: What to learn/research
            source: Where the request came from
            priority: 1-10, higher = more important
            
        Returns:
            The queued LearningTask
        """
        import uuid
        task_id = str(uuid.uuid4())[:8]
        
        task = LearningTask(
            id=task_id,
            type=type,
            description=description,
            source=source,
            priority=priority
        )
        
        self.pending_tasks[task_id] = task
        self._save_queue()
        
        logger.info(f"Queued learning task: {description}")
        return task
    
    def queue_news_collection(self, topics: List[str] = None):
        """Queue news collection for specified topics."""
        topics = topics or ["AI", "technology", "programming"]
        for topic in topics:
            self.queue_learning(
                type="news",
                description=f"Collect latest news on: {topic}",
                source="system",
                priority=3
            )
    
    def queue_skill_review(self):
        """Queue review of skill performance."""
        self.queue_learning(
            type="skill_review",
            description="Review skill success/failure rates and identify improvements",
            source="system",
            priority=7
        )
    
    def queue_upgrade_check(self):
        """Queue check for upgrade opportunities."""
        self.queue_learning(
            type="upgrade_check",
            description="Check for new tools, libraries, or capabilities to add",
            source="system",
            priority=5
        )
    
    def is_learning_hour(self) -> bool:
        """Check if we're currently in the learning hour."""
        now = datetime.now().time()
        return self.learning_start <= now <= self.learning_end
    
    def get_pending_tasks(self) -> List[LearningTask]:
        """Get all pending learning tasks sorted by priority."""
        return sorted(self.pending_tasks.values(), key=lambda t: t.priority, reverse=True)
    
    def get_completed_tasks(self, limit: int = 50) -> List[LearningTask]:
        """Get recently completed learning tasks."""
        return self.completed_tasks[-limit:]
    
    async def run_learning_session(self) -> Dict[str, Any]:
        """
        Execute the learning hour.
        Processes all pending tasks, requests approval for upgrades.
        """
        logger.info("Starting learning session")
        
        results = {
            "started_at": datetime.now().isoformat(),
            "tasks_processed": 0,
            "approvals_needed": [],
            "summaries": []
        }
        
        tasks = self.get_pending_tasks()
        
        for task in tasks:
            try:
                result = await self._process_learning_task(task)
                task.completed = True
                task.result = result
                
                self.completed_tasks.append(task)
                self.pending_tasks.pop(task.id, None)
                
                results["tasks_processed"] += 1
                
                if result.get("requires_approval"):
                    results["approvals_needed"].append({
                        "task_id": task.id,
                        "description": task.description,
                        "approval_type": result.get("approval_type")
                    })
                
                if result.get("summary"):
                    results["summaries"].append(result["summary"])
                    
            except Exception as e:
                logger.error(f"Failed to process learning task {task.id}: {e}")
        
        self._save_queue()
        
        results["completed_at"] = datetime.now().isoformat()
        
        # Emit event for completed learning session
        try:
            await self.event_bus.publish(Event(
                type=EventType.LEARNING_SESSION_COMPLETE,
                data=results
            ))
        except Exception:
            pass
        
        return results
    
    async def _process_learning_task(self, task: LearningTask) -> Dict[str, Any]:
        """Process a single learning task."""
        logger.info(f"Processing learning task: {task.description}")
        
        if task.type == "news":
            return await self._collect_news(task)
        elif task.type == "skill_review":
            return await self._review_skills(task)
        elif task.type == "upgrade_check":
            return await self._check_upgrades(task)
        elif task.type == "user_topic":
            return await self._research_topic(task)
        else:
            return {"success": False, "error": f"Unknown task type: {task.type}"}
    
    async def _collect_news(self, task: LearningTask) -> Dict[str, Any]:
        """Collect news for a topic."""
        # In practice, this would use web search
        return {
            "success": True,
            "summary": f"Collected news for: {task.description}",
            "items": []  # Would contain actual news items
        }
    
    async def _review_skills(self, task: LearningTask) -> Dict[str, Any]:
        """Review skill performance."""
        promoter = get_skill_promoter()
        skills = promoter.list_skills(status=SkillStatus.ACTIVE)
        
        # Find underperforming skills
        underperforming = []
        for skill in skills:
            total = skill.success_count + skill.failure_count
            if total >= 5:  # Enough data
                success_rate = skill.success_count / total
                if success_rate < 0.7:  # Less than 70% success
                    underperforming.append({
                        "skill": skill.name,
                        "success_rate": success_rate,
                        "recommendation": "Review and update steps"
                    })
        
        return {
            "success": True,
            "summary": f"Reviewed {len(skills)} skills, {len(underperforming)} need attention",
            "underperforming": underperforming
        }
    
    async def _check_upgrades(self, task: LearningTask) -> Dict[str, Any]:
        """Check for upgrade opportunities."""
        # Would check for new tools, libraries, etc.
        return {
            "success": True,
            "summary": "Checked for upgrades",
            "requires_approval": False,
            "upgrades_available": []
        }
    
    async def _research_topic(self, task: LearningTask) -> Dict[str, Any]:
        """Research a user-requested topic."""
        return {
            "success": True,
            "summary": f"Researched: {task.description}",
            "findings": []
        }
    
    def _scheduler_loop(self):
        """Background loop that checks if it's learning time."""
        while self._running:
            try:
                if self.is_learning_hour():
                    # Check if we have pending tasks
                    if self.pending_tasks:
                        logger.info("Learning hour active, running session")
                        asyncio.run(self.run_learning_session())
                
                # Sleep for 5 minutes before next check
                for _ in range(300):  # 5 minutes in 1-second chunks
                    if not self._running:
                        break
                    threading.Event().wait(1)
                    
            except Exception as e:
                logger.error(f"Learning scheduler error: {e}")
    
    def _load_queue(self):
        """Load pending tasks from disk."""
        queue_file = self.queue_dir / "pending.json"
        if queue_file.exists():
            try:
                data = json.loads(queue_file.read_text())
                for item in data:
                    task = LearningTask(
                        id=item["id"],
                        type=item["type"],
                        description=item["description"],
                        source=item["source"],
                        priority=item.get("priority", 5),
                        scheduled_at=datetime.fromisoformat(item["scheduled_at"])
                    )
                    self.pending_tasks[task.id] = task
            except Exception as e:
                logger.warning(f"Could not load learning queue: {e}")
    
    def _save_queue(self):
        """Save pending tasks to disk."""
        queue_file = self.queue_dir / "pending.json"
        data = [
            {
                "id": t.id,
                "type": t.type,
                "description": t.description,
                "source": t.source,
                "priority": t.priority,
                "scheduled_at": t.scheduled_at.isoformat()
            }
            for t in self.pending_tasks.values()
        ]
        queue_file.write_text(json.dumps(data, indent=2))


# Singleton instances
_skill_promoter: Optional[SkillPromoter] = None
_learning_scheduler: Optional[DailyLearningScheduler] = None


def get_skill_promoter() -> SkillPromoter:
    """Get or create the skill promoter singleton."""
    global _skill_promoter
    if _skill_promoter is None:
        _skill_promoter = SkillPromoter()
    return _skill_promoter


def get_learning_scheduler() -> DailyLearningScheduler:
    """Get or create the learning scheduler singleton."""
    global _learning_scheduler
    if _learning_scheduler is None:
        _learning_scheduler = DailyLearningScheduler()
    return _learning_scheduler
