"""Validate nested model output before it can enter persisted evidence."""
from pydantic import BaseModel, Field, StrictBool


class ClaimOutput(BaseModel):
    claim_text: str
    snippet_quote: str
    snippet_translation_vi: str = ""
    is_statistical: StrictBool = False


class SourceOutput(BaseModel):
    language: str = "unknown"
    summary_vi: str = ""
    author: str | None = None
    author_evidence: str = ""
    published_date: str | None = None
    date_evidence: str = ""
    claims: list[ClaimOutput] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ConflictOutput(BaseModel):
    claim_ids: list[str]
    description_vi: str = "Khác biệt cần đối chiếu."
    resolution_vi: str = "Giảng viên cần duyệt trước khi sử dụng."


class AgreementOutput(BaseModel):
    claim_ids: list[str]
    explanation_vi: str = ""


class CrossCheckOutput(BaseModel):
    conflicts: list[ConflictOutput] = Field(default_factory=list)
    agreements: list[AgreementOutput] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class LineOutput(BaseModel):
    text: str
    kind: str = "factual"
    claim_ids: list[str] = Field(default_factory=list)


class SceneOutput(BaseModel):
    scene_label: str
    visual_cue: str = ""
    speaker_note: str = ""
    lines: list[LineOutput]


class ScriptOutput(BaseModel):
    scenes: list[SceneOutput] = Field(min_length=1)


class AuditLineOutput(BaseModel):
    line_id: str
    has_factual_content: StrictBool
    supported: StrictBool
    reason_vi: str = ""


class AuditOutput(BaseModel):
    lines: list[AuditLineOutput]


class PatchLineOutput(LineOutput):
    line_id: str


class PatchOutput(BaseModel):
    lines: list[PatchLineOutput]


OUTPUT_SCHEMAS = {"evaluate_source": SourceOutput, "cross_check": CrossCheckOutput,
                  "write_script": ScriptOutput, "audit_script": AuditOutput, "patch_script": PatchOutput}
