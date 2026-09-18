"""A bounded Gemini suitability check, separate from research and writing.

Local rules reject obvious unsuitable requests before a client is constructed.
Every remaining lesson must receive a validated admission decision before paid
research begins. Each uncached evaluation makes one Gemini request, without
tools, grounding, or retries, then closes its synchronous client.
"""

import json
import threading

from config import settings
from services.admission_policy import ADMISSION_RESPONSE_SCHEMA, AdmissionPolicyService
from services.content_policy import validate_lesson_content
from services.llm_service import ServiceError, api_key_configured


MODERATION_TIMEOUT_MS = 20_000
MODERATION_MAX_OUTPUT_TOKENS = 768
MODERATION_MAX_INPUT_CHARS = 32_000
MODERATION_MAX_RESPONSE_CHARS = 16_000

_UNAVAILABLE = "Chưa thể kiểm tra mức độ phù hợp của bài học. Hãy thử lại sau; bước tìm tài liệu chưa được bắt đầu."


def moderation_model(config=None):
    config = config if config is not None else settings
    override = getattr(config, "moderation_model", "").strip()
    return override or getattr(config, "google_model", "").strip()


def _strict_object(raw):
    """Reject malformed, truncated, ambiguous or non-JSON responses locally."""
    if not isinstance(raw, str) or not raw.strip() or len(raw) > MODERATION_MAX_RESPONSE_CHARS:
        raise ValueError("Missing or oversized decision")

    def reject_constant(_value):
        raise ValueError("Non-JSON number")

    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate decision field")
            result[key] = value
        return result

    result = json.loads(raw, parse_constant=reject_constant, object_pairs_hook=unique_keys)
    if not isinstance(result, dict):
        raise ValueError("Decision must be a JSON object")
    return result


class GeminiModerationEvaluator:
    """Callable adapter consumed by AdmissionPolicyService; no live client at init."""

    def __init__(self, *, config=None):
        self.config = config if config is not None else settings

    def __call__(self, system: str, payload: dict) -> dict:
        # Configuration errors remain sanitized if this adapter is called on its
        # own; AdmissionPolicyService also maps them to its fail-closed result.
        key = getattr(self.config, "google_api_key", "").strip()
        model = moderation_model(self.config)
        if not api_key_configured(key) or not model:
            raise ServiceError(_UNAVAILABLE)
        client = None
        try:
            content = json.dumps(payload, ensure_ascii=False, allow_nan=False)
            if not isinstance(system, str) or not system.strip() or len(content) > MODERATION_MAX_INPUT_CHARS:
                raise ValueError("Invalid moderation input")
            from google import genai
            from google.genai import types

            client = genai.Client(
                api_key=key,
                vertexai=False,
                http_options=types.HttpOptions(
                    timeout=MODERATION_TIMEOUT_MS,
                    retry_options=types.HttpRetryOptions(attempts=1),
                ),
            )
            response = client.models.generate_content(
                model=model,
                contents=content,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                    response_json_schema=ADMISSION_RESPONSE_SCHEMA,
                    temperature=0,
                    candidate_count=1,
                    max_output_tokens=MODERATION_MAX_OUTPUT_TOKENS,
                    tools=[],
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                ),
            )
            candidates = getattr(response, "candidates", None)
            if not candidates or len(candidates) != 1:
                raise ValueError("Missing or ambiguous response candidate")
            finish = getattr(candidates[0], "finish_reason", None)
            finish = getattr(finish, "value", finish)
            if finish != "STOP":
                raise ValueError("Moderation response did not complete")
            return _strict_object(response.text)
        except Exception:
            # SDK messages may include credentials, request content or URLs.
            # No raw exception text or model output becomes a user-facing error.
            raise ServiceError(_UNAVAILABLE) from None
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    # Cleanup must not replace the sanitized provider failure.
                    pass


_admission_service = None
_admission_service_lock = threading.Lock()


def require_research_admission(payload):
    """Quick reject locally, then require a semantic decision (or valid cache)."""
    validate_lesson_content(payload)
    global _admission_service
    with _admission_service_lock:
        if _admission_service is None:
            _admission_service = AdmissionPolicyService(GeminiModerationEvaluator())
        service = _admission_service
    return service.require(payload)
