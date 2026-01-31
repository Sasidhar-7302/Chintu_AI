"""Persistence layer for Chintu v5.1 swarm execution state."""

from __future__ import annotations

import logging
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field
from sqlalchemy import (
    JSON,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    event,
    inspect,
    text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

logger = logging.getLogger(__name__)


class ProjectStatus(str, Enum):
    PLANNING = "PLANNING"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    BLOCKED = "BLOCKED"
    DONE = "DONE"


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ProjectStatus] = mapped_column(
        SAEnum(ProjectStatus), default=ProjectStatus.PLANNING, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    tasks: Mapped[List["Task"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    daily_logs: Mapped[List["DailyLog"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[TaskStatus] = mapped_column(
        SAEnum(TaskStatus), default=TaskStatus.PENDING, nullable=False
    )
    dependencies: Mapped[List[int]] = mapped_column(JSON, default=list, nullable=False)
    assigned_agent: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    output_artifact: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    project: Mapped[Project] = relationship(back_populates="tasks")


class DailyLog(Base):
    __tablename__ = "daily_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    project: Mapped[Project] = relationship(back_populates="daily_logs")


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    goal: str = Field(..., min_length=1)
    status: ProjectStatus = ProjectStatus.PLANNING


class TaskCreate(BaseModel):
    project_id: int = Field(..., ge=1)
    description: str = Field(..., min_length=1)
    status: TaskStatus = TaskStatus.PENDING
    dependencies: List[int] = Field(default_factory=list)
    assigned_agent: Optional[str] = Field(default=None, max_length=64)
    output_artifact: Optional[str] = None


class DailyLogCreate(BaseModel):
    project_id: int = Field(..., ge=1)
    summary: str = Field(..., min_length=1, max_length=2000)


_ENGINE_CACHE: dict[str, Engine] = {}


def _enable_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def get_engine(db_path: Path) -> Engine:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    cache_key = str(db_path)
    engine = _ENGINE_CACHE.get(cache_key)
    if engine:
        return engine
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    event.listen(engine, "connect", _enable_sqlite_pragmas)
    _ENGINE_CACHE[cache_key] = engine
    return engine


def get_sqlite_journal_mode(engine: Engine) -> str:
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA journal_mode"))
        mode = result.scalar()
    return str(mode or "")


class SwarmStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.engine = get_engine(self.db_path)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)

    def init(self) -> None:
        Base.metadata.create_all(self.engine)
        logger.info("Swarm database initialized: %s", self.db_path)

    def table_names(self) -> List[str]:
        return inspect(self.engine).get_table_names()

    def journal_mode(self) -> str:
        return get_sqlite_journal_mode(self.engine)

    def create_project(self, data: ProjectCreate | dict) -> Project:
        if not isinstance(data, ProjectCreate):
            data = ProjectCreate.model_validate(data)
        project = Project(name=data.name, goal=data.goal, status=data.status)
        with self.Session() as session:
            session.add(project)
            session.commit()
            session.refresh(project)
        return project

    def create_task(self, data: TaskCreate | dict) -> Task:
        if not isinstance(data, TaskCreate):
            data = TaskCreate.model_validate(data)
        task = Task(
            project_id=data.project_id,
            description=data.description,
            status=data.status,
            dependencies=list(data.dependencies),
            assigned_agent=data.assigned_agent,
            output_artifact=data.output_artifact,
        )
        with self.Session() as session:
            session.add(task)
            session.commit()
            session.refresh(task)
        return task

    def create_daily_log(self, data: DailyLogCreate | dict) -> DailyLog:
        if not isinstance(data, DailyLogCreate):
            data = DailyLogCreate.model_validate(data)
        log = DailyLog(project_id=data.project_id, summary=data.summary)
        with self.Session() as session:
            session.add(log)
            session.commit()
            session.refresh(log)
        return log

    def get_tasks(self, project_id: int) -> List[Task]:
        with self.Session() as session:
            return list(
                session.query(Task).filter(Task.project_id == project_id).order_by(Task.id).all()
            )

    def update_task_status(
        self,
        task_id: int,
        status: TaskStatus,
        output_artifact: Optional[str] = None,
    ) -> Optional[Task]:
        with self.Session() as session:
            task = session.get(Task, task_id)
            if not task:
                return None
            task.status = status
            if output_artifact is not None:
                task.output_artifact = output_artifact
            session.commit()
            session.refresh(task)
            return task


def init_swarm_db(db_path: Optional[Path] = None) -> SwarmStore:
    if db_path is None:
        from chintu_backend.core.config import get_config

        config = get_config()
        db_path = config.swarm_db_path
    store = SwarmStore(db_path)
    store.init()
    return store
