"""
Entity Graph - Knowledge graph for entities and relationships.

Tracks relationships between:
- People (contacts, collaborators)
- Projects 
- Dates/Events
- Topics/Skills
- Resources (files, URLs, credentials)
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict

from chintu_backend.core.config import get_config

logger = logging.getLogger(__name__)


class EntityType(Enum):
    PERSON = "person"
    PROJECT = "project"
    DATE = "date"
    EVENT = "event"
    TOPIC = "topic"
    SKILL = "skill"
    RESOURCE = "resource"
    LOCATION = "location"
    ORGANIZATION = "organization"
    TASK = "task"


class RelationType(Enum):
    # Person relationships
    WORKS_ON = "works_on"
    KNOWS = "knows"
    MANAGES = "manages"
    REPORTS_TO = "reports_to"
    COLLABORATES_WITH = "collaborates_with"
    
    # Project relationships
    DEPENDS_ON = "depends_on"
    PART_OF = "part_of"
    USES = "uses"
    PRODUCES = "produces"
    
    # Time relationships
    SCHEDULED_FOR = "scheduled_for"
    HAPPENED_ON = "happened_on"
    DUE_ON = "due_on"
    STARTED_ON = "started_on"
    COMPLETED_ON = "completed_on"
    
    # Topic relationships
    RELATED_TO = "related_to"
    SUBTOPIC_OF = "subtopic_of"
    REQUIRES = "requires"
    
    # Resource relationships
    STORED_AT = "stored_at"
    ACCESSED_BY = "accessed_by"
    OWNED_BY = "owned_by"


@dataclass
class Entity:
    """An entity in the knowledge graph."""
    id: str
    name: str
    type: EntityType
    properties: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    aliases: List[str] = field(default_factory=list)
    importance: float = 0.5  # 0-1, for prioritization


@dataclass
class Relationship:
    """A relationship between two entities."""
    id: str
    source_id: str
    target_id: str
    type: RelationType
    properties: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0  # 0-1
    created_at: datetime = field(default_factory=datetime.now)


class EntityGraph:
    """
    Knowledge graph for tracking entities and their relationships.
    
    Features:
    - Store entities (people, projects, topics, etc.)
    - Track relationships between entities
    - Extract entities from text
    - Query related entities
    - Daily reflection/summary generation
    """
    
    def __init__(self):
        self.config = get_config()
        self.graph_dir = self.config.data_dir / "entity_graph"
        self.graph_dir.mkdir(parents=True, exist_ok=True)
        
        self.entities: Dict[str, Entity] = {}
        self.relationships: Dict[str, Relationship] = {}
        
        # Indexes for fast lookup
        self._by_type: Dict[EntityType, Set[str]] = defaultdict(set)
        self._by_name: Dict[str, str] = {}  # lowercase name → entity_id
        self._outgoing: Dict[str, Set[str]] = defaultdict(set)  # entity_id → relationship_ids
        self._incoming: Dict[str, Set[str]] = defaultdict(set)
        
        self._load()
    
    # --- Entity CRUD ---
    
    def add_entity(
        self,
        name: str,
        type: EntityType,
        properties: Dict[str, Any] = None,
        aliases: List[str] = None,
        importance: float = 0.5
    ) -> Entity:
        """Add a new entity to the graph."""
        import uuid
        entity_id = str(uuid.uuid4())[:8]
        
        entity = Entity(
            id=entity_id,
            name=name,
            type=type,
            properties=properties or {},
            aliases=aliases or [],
            importance=importance
        )
        
        self.entities[entity_id] = entity
        self._by_type[type].add(entity_id)
        self._by_name[name.lower()] = entity_id
        
        for alias in entity.aliases:
            self._by_name[alias.lower()] = entity_id
        
        self._save()
        logger.info(f"Added entity: {name} ({type.value})")
        return entity
    
    def get_entity(self, entity_id: str) -> Optional[Entity]:
        """Get entity by ID."""
        return self.entities.get(entity_id)
    
    def find_entity(self, name: str) -> Optional[Entity]:
        """Find entity by name or alias."""
        entity_id = self._by_name.get(name.lower())
        if entity_id:
            return self.entities.get(entity_id)
        return None
    
    def update_entity(self, entity_id: str, **updates) -> bool:
        """Update entity properties."""
        entity = self.entities.get(entity_id)
        if not entity:
            return False
        
        for key, value in updates.items():
            if key == "properties":
                entity.properties.update(value)
            elif hasattr(entity, key):
                setattr(entity, key, value)
        
        entity.updated_at = datetime.now()
        self._save()
        return True
    
    def delete_entity(self, entity_id: str) -> bool:
        """Delete entity and all its relationships."""
        entity = self.entities.get(entity_id)
        if not entity:
            return False
        
        # Remove relationships
        rel_ids = list(self._outgoing.get(entity_id, set())) + \
                  list(self._incoming.get(entity_id, set()))
        for rel_id in rel_ids:
            self.delete_relationship(rel_id)
        
        # Remove from indexes
        self._by_type[entity.type].discard(entity_id)
        self._by_name.pop(entity.name.lower(), None)
        for alias in entity.aliases:
            self._by_name.pop(alias.lower(), None)
        
        # Remove entity
        del self.entities[entity_id]
        self._save()
        return True
    
    # --- Relationship CRUD ---
    
    def add_relationship(
        self,
        source_id: str,
        target_id: str,
        type: RelationType,
        properties: Dict[str, Any] = None,
        confidence: float = 1.0
    ) -> Optional[Relationship]:
        """Add a relationship between two entities."""
        if source_id not in self.entities or target_id not in self.entities:
            return None
        
        import uuid
        rel_id = str(uuid.uuid4())[:8]
        
        relationship = Relationship(
            id=rel_id,
            source_id=source_id,
            target_id=target_id,
            type=type,
            properties=properties or {},
            confidence=confidence
        )
        
        self.relationships[rel_id] = relationship
        self._outgoing[source_id].add(rel_id)
        self._incoming[target_id].add(rel_id)
        
        self._save()
        
        source = self.entities[source_id]
        target = self.entities[target_id]
        logger.info(f"Added relationship: {source.name} --{type.value}--> {target.name}")
        return relationship
    
    def get_relationships(
        self,
        entity_id: str,
        direction: str = "both",
        rel_type: RelationType = None
    ) -> List[Relationship]:
        """Get relationships for an entity."""
        rel_ids = set()
        
        if direction in ("out", "both"):
            rel_ids.update(self._outgoing.get(entity_id, set()))
        if direction in ("in", "both"):
            rel_ids.update(self._incoming.get(entity_id, set()))
        
        relationships = [self.relationships[rid] for rid in rel_ids if rid in self.relationships]
        
        if rel_type:
            relationships = [r for r in relationships if r.type == rel_type]
        
        return relationships
    
    def delete_relationship(self, rel_id: str) -> bool:
        """Delete a relationship."""
        rel = self.relationships.get(rel_id)
        if not rel:
            return False
        
        self._outgoing[rel.source_id].discard(rel_id)
        self._incoming[rel.target_id].discard(rel_id)
        del self.relationships[rel_id]
        
        return True
    
    # --- Queries ---
    
    def get_related_entities(
        self,
        entity_id: str,
        rel_types: List[RelationType] = None,
        max_depth: int = 1
    ) -> List[Entity]:
        """Get entities related to the given entity."""
        visited = {entity_id}
        result = []
        current_level = {entity_id}
        
        for depth in range(max_depth):
            next_level = set()
            
            for eid in current_level:
                for rel in self.get_relationships(eid):
                    if rel_types and rel.type not in rel_types:
                        continue
                    
                    other_id = rel.target_id if rel.source_id == eid else rel.source_id
                    
                    if other_id not in visited:
                        visited.add(other_id)
                        next_level.add(other_id)
                        entity = self.entities.get(other_id)
                        if entity:
                            result.append(entity)
            
            current_level = next_level
        
        return result
    
    def get_entities_by_type(self, type: EntityType) -> List[Entity]:
        """Get all entities of a specific type."""
        entity_ids = self._by_type.get(type, set())
        return [self.entities[eid] for eid in entity_ids if eid in self.entities]
    
    def search_entities(self, query: str, types: List[EntityType] = None) -> List[Entity]:
        """Search entities by name."""
        query_lower = query.lower()
        results = []
        
        for entity in self.entities.values():
            if types and entity.type not in types:
                continue
            
            if query_lower in entity.name.lower():
                results.append(entity)
            elif any(query_lower in alias.lower() for alias in entity.aliases):
                results.append(entity)
        
        return sorted(results, key=lambda e: e.importance, reverse=True)
    
    # --- Entity Extraction ---
    
    def extract_entities_from_text(self, text: str) -> List[Dict[str, Any]]:
        """
        Extract entities from text using pattern matching and LLM.
        Returns list of extracted entities with their types.
        """
        extracted = []
        
        # Pattern-based extraction
        patterns = {
            EntityType.DATE: [
                r'\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b',
                r'\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b',
                r'\b(today|tomorrow|yesterday|next week|next month)\b',
            ],
            EntityType.PERSON: [
                r'\b([A-Z][a-z]+\s+[A-Z][a-z]+)\b',  # Two capitalized words
            ],
            EntityType.RESOURCE: [
                r'https?://[^\s]+',
                r'\b[\w.-]+@[\w.-]+\.\w+\b',  # Email
            ],
        }
        
        for entity_type, type_patterns in patterns.items():
            for pattern in type_patterns:
                matches = re.findall(pattern, text, re.IGNORECASE)
                for match in matches:
                    extracted.append({
                        "name": match if isinstance(match, str) else match[0],
                        "type": entity_type,
                        "confidence": 0.7
                    })
        
        # LLM-based extraction for complex entities
        try:
            llm_entities = self._llm_extract_entities(text)
            extracted.extend(llm_entities)
        except Exception as e:
            logger.warning(f"LLM entity extraction failed: {e}")
        
        return extracted
    
    def _llm_extract_entities(self, text: str) -> List[Dict[str, Any]]:
        """Use LLM to extract entities from text."""
        try:
            from chintu_backend.brain.llm.ollama_client import OllamaClient
            
            llm = OllamaClient(
                host=getattr(self.config, 'ollama_host', 'http://localhost:11434'),
                model=getattr(self.config, 'ollama_model', 'qwen2.5:3b')
            )
            
            prompt = f"""Extract entities from this text. Look for:
- People (names)
- Projects (product/app names)
- Organizations (companies)
- Topics/Skills (technologies, concepts)
- Events (meetings, deadlines)

TEXT: {text[:1000]}

Output as JSON array:
[{{"name": "entity name", "type": "person|project|organization|topic|event", "confidence": 0.8}}]"""
            
            response = llm.generate(prompt) if hasattr(llm, 'generate') else llm.chat(prompt)
            
            # Parse JSON
            if "[" in response and "]" in response:
                start = response.find("[")
                end = response.rfind("]") + 1
                entities = json.loads(response[start:end])
                
                # Convert type strings to EntityType
                for e in entities:
                    type_str = e.get("type", "topic").lower()
                    type_map = {
                        "person": EntityType.PERSON,
                        "project": EntityType.PROJECT,
                        "organization": EntityType.ORGANIZATION,
                        "topic": EntityType.TOPIC,
                        "skill": EntityType.SKILL,
                        "event": EntityType.EVENT,
                    }
                    e["type"] = type_map.get(type_str, EntityType.TOPIC)
                
                return entities
            
            return []
            
        except Exception as e:
            logger.debug(f"LLM extraction failed: {e}")
            return []
    
    def ingest_entities(self, entities: List[Dict[str, Any]]) -> List[Entity]:
        """Add extracted entities to the graph."""
        added = []
        
        for e in entities:
            # Check if entity already exists
            existing = self.find_entity(e["name"])
            if existing:
                # Update importance based on frequency
                existing.importance = min(1.0, existing.importance + 0.1)
                existing.updated_at = datetime.now()
                added.append(existing)
            else:
                entity = self.add_entity(
                    name=e["name"],
                    type=e["type"],
                    importance=e.get("confidence", 0.5)
                )
                added.append(entity)
        
        return added
    
    # --- Daily Reflection ---
    
    def generate_daily_summary(self) -> Dict[str, Any]:
        """Generate a daily summary of key entities and relationships."""
        today = datetime.now().date()
        
        # Get recently updated entities
        recent_entities = sorted(
            self.entities.values(),
            key=lambda e: e.updated_at,
            reverse=True
        )[:20]
        
        # Get high-importance entities
        important_entities = sorted(
            self.entities.values(),
            key=lambda e: e.importance,
            reverse=True
        )[:10]
        
        # Group by type
        by_type = defaultdict(list)
        for e in recent_entities:
            by_type[e.type.value].append(e.name)
        
        # Get key relationships
        key_relationships = []
        for rel in sorted(self.relationships.values(), 
                         key=lambda r: r.confidence, reverse=True)[:10]:
            source = self.entities.get(rel.source_id)
            target = self.entities.get(rel.target_id)
            if source and target:
                key_relationships.append({
                    "source": source.name,
                    "relation": rel.type.value,
                    "target": target.name
                })
        
        summary = {
            "date": today.isoformat(),
            "total_entities": len(self.entities),
            "total_relationships": len(self.relationships),
            "recent_entities": {k: v for k, v in by_type.items()},
            "important_entities": [e.name for e in important_entities],
            "key_relationships": key_relationships,
            "entity_counts": {
                t.value: len(ids) for t, ids in self._by_type.items()
            }
        }
        
        return summary
    
    # --- Persistence ---
    
    def _load(self):
        """Load graph from disk."""
        entities_file = self.graph_dir / "entities.json"
        relationships_file = self.graph_dir / "relationships.json"
        
        if entities_file.exists():
            try:
                data = json.loads(entities_file.read_text())
                for item in data:
                    entity = Entity(
                        id=item["id"],
                        name=item["name"],
                        type=EntityType(item["type"]),
                        properties=item.get("properties", {}),
                        created_at=datetime.fromisoformat(item["created_at"]),
                        updated_at=datetime.fromisoformat(item.get("updated_at", item["created_at"])),
                        aliases=item.get("aliases", []),
                        importance=item.get("importance", 0.5)
                    )
                    self.entities[entity.id] = entity
                    self._by_type[entity.type].add(entity.id)
                    self._by_name[entity.name.lower()] = entity.id
                    for alias in entity.aliases:
                        self._by_name[alias.lower()] = entity.id
            except Exception as e:
                logger.warning(f"Could not load entities: {e}")
        
        if relationships_file.exists():
            try:
                data = json.loads(relationships_file.read_text())
                for item in data:
                    rel = Relationship(
                        id=item["id"],
                        source_id=item["source_id"],
                        target_id=item["target_id"],
                        type=RelationType(item["type"]),
                        properties=item.get("properties", {}),
                        confidence=item.get("confidence", 1.0),
                        created_at=datetime.fromisoformat(item["created_at"])
                    )
                    self.relationships[rel.id] = rel
                    self._outgoing[rel.source_id].add(rel.id)
                    self._incoming[rel.target_id].add(rel.id)
            except Exception as e:
                logger.warning(f"Could not load relationships: {e}")
    
    def _save(self):
        """Save graph to disk."""
        entities_file = self.graph_dir / "entities.json"
        relationships_file = self.graph_dir / "relationships.json"
        
        entities_data = [
            {
                "id": e.id,
                "name": e.name,
                "type": e.type.value,
                "properties": e.properties,
                "created_at": e.created_at.isoformat(),
                "updated_at": e.updated_at.isoformat(),
                "aliases": e.aliases,
                "importance": e.importance
            }
            for e in self.entities.values()
        ]
        entities_file.write_text(json.dumps(entities_data, indent=2))
        
        relationships_data = [
            {
                "id": r.id,
                "source_id": r.source_id,
                "target_id": r.target_id,
                "type": r.type.value,
                "properties": r.properties,
                "confidence": r.confidence,
                "created_at": r.created_at.isoformat()
            }
            for r in self.relationships.values()
        ]
        relationships_file.write_text(json.dumps(relationships_data, indent=2))


# Singleton
_entity_graph: Optional[EntityGraph] = None


def get_entity_graph() -> EntityGraph:
    """Get or create the entity graph singleton."""
    global _entity_graph
    if _entity_graph is None:
        _entity_graph = EntityGraph()
    return _entity_graph
