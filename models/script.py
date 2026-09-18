from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field

class SourceReference(BaseModel):
    source_id: str
    claim_id: str = ""
    snippet_quote: str = ""
    url: str = ""
    is_verified: bool = False
    verification_score: float = 0.0
    snippet_translation_vi: str = ""
    source_context: str = ""
    match_start: Optional[int] = None
    match_end: Optional[int] = None

class ScriptLine(BaseModel):
    line_id: str = Field(default_factory=lambda: f"ln_{uuid.uuid4().hex[:8]}")
    text: str
    source_refs: list[SourceReference] = Field(default_factory=list)
    has_factual_content: bool = False
    is_unverified: bool = False
    hallucination_detected: bool = False
    word_count: int = 0
    kind: str = "factual"
    verification_note: str = ""

    def model_post_init(self, __context) -> None:
        if self.word_count == 0 and self.text:
            self.word_count = len(self.text.split())

class Scene(BaseModel):
    scene_id: str = Field(default_factory=lambda: f"sc_{uuid.uuid4().hex[:8]}")
    scene_number: int
    scene_label: str
    estimated_duration_seconds: int = 0
    lines: list[ScriptLine] = Field(default_factory=list)
    visual_cue: str = ""
    speaker_note: str = ""

    @property
    def total_words(self) -> int:
        return sum(ln.word_count for ln in self.lines)

class VideoScript(BaseModel):
    script_id: str = Field(default_factory=lambda: f"scr_{uuid.uuid4().hex[:8]}")
    topic: str
    target_audience: str = ""
    objectives: list[str] = Field(default_factory=list)
    target_duration_minutes: float = 5.0
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    scenes: list[Scene] = Field(default_factory=list)
    dependency_graph: dict[str, list[str]] = Field(default_factory=dict)
    teaching_style: str = ""
    output_language: str = "vi"
    estimated_duration_minutes: float = 0.0
    warnings: list[str] = Field(default_factory=list)
    verification_summary: dict = Field(default_factory=dict)

    def build_dependency_graph(self) -> None:
        self.dependency_graph.clear()
        for sc in self.scenes:
            for ln in sc.lines:
                for ref in ln.source_refs:
                    if ref.source_id not in self.dependency_graph:
                        self.dependency_graph[ref.source_id] = []
                    if ln.line_id not in self.dependency_graph[ref.source_id]:
                        self.dependency_graph[ref.source_id].append(ln.line_id)
