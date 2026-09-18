from __future__ import annotations
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field

class SourceStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    UNREACHABLE = "unreachable"

class RawSource(BaseModel):
    source_id: str = Field(default_factory=lambda: f"src_{uuid.uuid4().hex[:8]}")
    url: str
    title: str = ""
    raw_markdown: str = ""
    http_status: int = 0
    error_message: Optional[str] = None
    error: Optional[str] = None
    language: str = "unknown"
    author: str = "Không rõ"
    published_date: Optional[str] = None
    fetched_at: Optional[datetime] = None
    content_hash: str = ""
    final_url: str = ""
    content_type: str = ""
    original_url: str = ""
    retrieval_method: str = "direct"
    retrieval_note: str = ""
    retrieval_details: list[str] = Field(default_factory=list)
    document_doi: str = ""
    document_pmcid: str = ""
    warnings: list[str] = Field(default_factory=list)
    has_prompt_injection: bool = False
    injection_details: Optional[str] = None

    @property
    def is_accessible(self) -> bool:
        return (
            200 <= self.http_status < 300
            and not self.error_message
            and not self.error
            and len(self.raw_markdown.strip()) >= 80
        )

class TrustScoreBreakdown(BaseModel):
    domain_authority: float = Field(ge=0, le=100)
    recency: float = Field(ge=0, le=100)
    evidence_quality: float = Field(ge=0, le=100)
    author_credibility: float = Field(ge=0, le=100)

    @property
    def weighted_total(self) -> float:
        return round(
            self.domain_authority * 0.30
            + self.recency * 0.25
            + self.evidence_quality * 0.25
            + self.author_credibility * 0.20,
            1,
        )

class ExtractedClaim(BaseModel):
    claim_id: str = Field(default_factory=lambda: f"clm_{uuid.uuid4().hex[:8]}")
    source_id: str
    claim_text: str
    snippet_quote: str
    is_statistical: bool = False
    is_verified: bool = False
    verification_score: float = 0.0
    snippet_translation_vi: str = ""
    source_context: str = ""
    translation_vi: str = ""
    verification_note: str = ""
    match_start: Optional[int] = None
    match_end: Optional[int] = None

class SourceItem(BaseModel):
    source_id: str
    url: str
    title: str
    author: str = "Không rõ"
    published_date: Optional[str] = None
    language: str = "unknown"
    status: SourceStatus = SourceStatus.PENDING
    trust_score: float = 0.0
    trust_breakdown: TrustScoreBreakdown
    trust_reasoning: str = ""
    claims: list[ExtractedClaim] = Field(default_factory=list)
    has_prompt_injection: bool = False
    injection_details: Optional[str] = None
    is_outdated: bool = False
    summary_vi: str = ""
    warnings: list[str] = Field(default_factory=list)
    is_accessible: bool = False
    error_message: Optional[str] = None
    error: Optional[str] = None
    fetched_at: Optional[datetime] = None
    content_hash: str = ""
    final_url: str = ""
    content_type: str = ""
    original_url: str = ""
    retrieval_method: str = "direct"
    retrieval_note: str = ""
    retrieval_details: list[str] = Field(default_factory=list)

class ConflictWarning(BaseModel):
    conflict_id: str = Field(default_factory=lambda: f"cfl_{uuid.uuid4().hex[:8]}")
    topic: str
    source_a_id: str
    source_a_claim: str
    source_a_value: str = ""
    source_b_id: str
    source_b_claim: str
    source_b_value: str = ""

class Dossier(BaseModel):
    topic: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    search_queries_used: list[str] = Field(default_factory=list)
    total_urls_scanned: int = 0
    sources: list[SourceItem] = Field(default_factory=list)
    conflicts: list[ConflictWarning] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    search_query_details: list[dict] = Field(default_factory=list)
    trust_rubric: str = "Điểm hỗ trợ sàng lọc; không phải xác nhận độ đúng của nội dung."
