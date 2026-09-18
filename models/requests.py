from pydantic import BaseModel, Field, field_validator
from models.limits import MAX_SOURCES


LANGUAGES = {"vi", "en", "fr", "de", "es", "ja", "ko", "zh"}


class PipelineRequest(BaseModel):
    topic: str = Field(min_length=3, max_length=500)
    target_audience: str = Field(min_length=2, max_length=1000)
    objectives: list[str] = Field(min_length=1, max_length=12)
    duration_minutes: float = Field(default=5.0, ge=1, le=15)
    teaching_style: str = Field(default="Giải thích rõ ràng, gần gũi; đi từ ví dụ đến khái niệm và đặt câu hỏi gợi mở.", max_length=5000)
    source_languages: list[str] = Field(default_factory=lambda: ["vi", "en"], min_length=1, max_length=8)
    max_sources: int = Field(default=6, ge=3, le=MAX_SOURCES)

    @field_validator("topic", "target_audience", "teaching_style", mode="before")
    @classmethod
    def trim_strings(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("objectives")
    @classmethod
    def clean_objectives(cls, value):
        if any(not item.strip() or len(item) > 1000 for item in value):
            raise ValueError("Mỗi mục tiêu phải có nội dung và không quá 1.000 ký tự.")
        return list(dict.fromkeys(item.strip() for item in value))

    @field_validator("source_languages")
    @classmethod
    def supported_languages(cls, value):
        if set(value) - LANGUAGES:
            raise ValueError("Ngôn ngữ hỗ trợ: vi, en, fr, de, es, ja, ko, zh.")
        return list(dict.fromkeys(value))


class ReviewRequest(BaseModel):
    session_id: str
    approved_source_ids: list[str] = Field(min_length=1, max_length=MAX_SOURCES)
    rejected_source_ids: list[str] = Field(default_factory=list, max_length=MAX_SOURCES)


class PatchRequest(BaseModel):
    session_id: str
    remove_source_ids: list[str] = Field(min_length=1, max_length=MAX_SOURCES)


class AddSourceRequest(BaseModel):
    session_id: str
    url: str = Field(min_length=8, max_length=2048)


class RetrySourceRequest(BaseModel):
    session_id: str
    source_id: str
