from typing import TypedDict, Optional

class ScriptScoutState(TypedDict, total=False):
    topic: str
    target_audience: str
    objectives: list[str]
    duration_minutes: float
    teaching_style: str
    source_languages: list[str]
    target_word_count: int

    search_queries: list[str]
    raw_sources: list[dict]

    dossier: dict
    conflicts: list[dict]
    active_source_ids: list[str]

    script: dict
    dependency_graph: dict

    verification_results: list[dict]
    hallucination_count: int

    removed_source_ids: list[str]
    affected_line_ids: list[str]
    patch_applied: bool

    current_step: str
    error_message: Optional[str]
    messages: list
