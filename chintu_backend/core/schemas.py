"""Strict Pydantic schemas for Chintu capabilities (Data Layer Hardening)."""

from typing import Optional, List
from pydantic import BaseModel, Field

class OpenAppSchema(BaseModel):
    app_name: str = Field(..., description="Name of the application to open")

class OpenUrlSchema(BaseModel):
    url: str = Field(..., description="Full URL to open (must include http/https)")

class ReminderSchema(BaseModel):
    content: str = Field(..., description="What to remind about")
    time: Optional[str] = Field(None, description="Time of the reminder (ISO or relative)")

class NoteSchema(BaseModel):
    content: str = Field(..., description="Note content to save")
    title: Optional[str] = Field(None, description="Optional title for the note")

class SearchSchema(BaseModel):
    query: str = Field(..., description="Search query")

class RecallSchema(BaseModel):
    query: str = Field(..., description="Topic or question to recall information about")

class CodeExecutionSchema(BaseModel):
    goal: str = Field(..., description="The logic/math goal for the code interpreter")

class SwarmSchema(BaseModel):
    task: str = Field(..., description="The complex task for the multi-agent swarm")
