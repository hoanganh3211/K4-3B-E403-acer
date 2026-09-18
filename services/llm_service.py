"""Small, synchronous JSON adapter shared by every research/writing step.

Provider responses are never substituted with demonstration content. Domain
schemas are validated by the caller, after this layer validates the JSON object.
"""

import json
from typing import Any

from config import settings


class ServiceError(RuntimeError):
    """An actionable error whose message is safe to display to the user."""


def api_key_configured(value: str | None) -> bool:
    """Reject empty/example credentials locally without echoing their value."""
    key = (value or "").strip().lower()
    return bool(key) and key not in {"replace_me", "replace-me", "changeme", "xxx", "..."} and not key.startswith(
        ("your_", "your-", "sk-your", "tvly-your", "<your", "<api")
    )


def provider_error(provider: str, exc: Exception) -> str:
    """Do not include SDK messages: they may contain keys, URLs or input text."""
    code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if code in (401, 403):
        return f"{provider} từ chối xác thực. Kiểm tra API key và quyền truy cập trong .env."
    if code == 404:
        return f"{provider} không tìm thấy model hoặc endpoint. Kiểm tra tên model và quyền truy cập."
    if code in (429, 432):
        return f"{provider} đã hết hạn mức hoặc đang giới hạn lượt gọi. Kiểm tra quota rồi thử lại."
    if code in (400, 413, 422):
        return f"{provider} không chấp nhận yêu cầu. Kiểm tra model hỗ trợ JSON và giới hạn đầu vào."
    if "timeout" in type(exc).__name__.lower():
        return f"{provider} phản hồi quá thời gian cho phép. Vui lòng thử lại."
    return f"Không thể kết nối hoặc nhận kết quả hợp lệ từ {provider}. Kiểm tra kết nối và cấu hình dịch vụ."


class LLMService:
    def __init__(self, provider: str | None = None, *, config=None, client=None):
        self.config = config if config is not None else settings
        self.provider = (provider or self.config.llm_provider).strip().lower()
        if self.provider == "gemini":
            self.provider = "google"
        if self.provider not in ("openai", "google"):
            raise ServiceError("LLM_PROVIDER phải là openai hoặc google.")
        self.model = getattr(self.config, f"{self.provider}_model", "").strip()
        if not self.model:
            raise ServiceError("Chưa cấu hình tên model trong .env.")
        self.timeout = float(getattr(self.config, "llm_timeout_seconds", 90))
        self.max_tokens = int(getattr(self.config, "max_tokens", 12000))
        self.usage: list[dict[str, Any]] = []
        self._owns_client = client is None
        self.client = client if client is not None else self._create_client()

    def _create_client(self):
        api_key = getattr(self.config, f"{self.provider}_api_key", "").strip()
        if not api_key_configured(api_key):
            setting = "OPENAI_API_KEY" if self.provider == "openai" else "GOOGLE_API_KEY"
            raise ServiceError(f"Thiếu {setting} hợp lệ hoặc đang dùng giá trị mẫu. Thêm API key thật vào .env rồi khởi động lại ứng dụng.")
        try:
            if self.provider == "openai":
                from openai import OpenAI

                options = {"api_key": api_key, "timeout": self.timeout, "max_retries": 1}
                base_url = getattr(self.config, "openai_base_url", None)
                if base_url:
                    options["base_url"] = base_url
                return OpenAI(**options)
            from google import genai
            from google.genai import types

            return genai.Client(
                api_key=api_key,
                http_options=types.HttpOptions(
                    timeout=int(self.timeout * 1000),
                    retry_options=types.HttpRetryOptions(attempts=2),
                ),
            )
        except ImportError:
            package = "openai" if self.provider == "openai" else "google-genai"
            raise ServiceError(f"Thiếu thư viện {package}. Chạy pip install -r requirements.txt.") from None
        except Exception as exc:
            raise ServiceError(provider_error(self.provider, exc)) from None

    def generate_json(self, system: str, payload: dict) -> dict:
        """Return a JSON object or fail explicitly, including on truncated output."""
        system = system + "\nReturn exactly one valid JSON object. Do not wrap it in Markdown."
        try:
            content = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError):
            raise ServiceError("Dữ liệu đầu vào cho model không phải JSON hợp lệ.") from None

        try:
            if self.provider == "openai":
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": content},
                    ],
                    response_format={"type": "json_object"},
                    max_completion_tokens=self.max_tokens,
                )
                self._record_usage(getattr(response, "usage", None), "prompt_tokens", "completion_tokens")
                choices = getattr(response, "choices", None)
                if not choices:
                    raise ServiceError("Model không trả về nội dung. Vui lòng thử lại.")
                choice = choices[0]
                if choice.finish_reason == "length":
                    raise ServiceError("Phản hồi model bị cắt do giới hạn token. Tăng MAX_TOKENS hoặc giảm độ dài bài giảng.")
                if getattr(choice.message, "refusal", None) or choice.finish_reason == "content_filter":
                    raise ServiceError("Model không thể xử lý nội dung này. Điều chỉnh chủ đề hoặc tài liệu đầu vào.")
                raw = choice.message.content
            else:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=content,
                    config={
                        "system_instruction": system,
                        "response_mime_type": "application/json",
                        "max_output_tokens": self.max_tokens,
                    },
                )
                self._record_usage(getattr(response, "usage_metadata", None), "prompt_token_count", "candidates_token_count")
                candidates = getattr(response, "candidates", None)
                if candidates:
                    finish = str(getattr(candidates[0], "finish_reason", ""))
                    if "MAX_TOKENS" in finish:
                        raise ServiceError("Phản hồi model bị cắt do giới hạn token. Tăng MAX_TOKENS hoặc giảm độ dài bài giảng.")
                    if any(reason in finish for reason in ("SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT")):
                        raise ServiceError("Model không thể xử lý nội dung này. Điều chỉnh chủ đề hoặc tài liệu đầu vào.")
                raw = response.text
        except ServiceError:
            raise
        except Exception as exc:
            raise ServiceError(provider_error(self.provider, exc)) from None

        try:
            # Python's default decoder accepts NaN/Infinity, which are not JSON.
            def invalid_constant(value):
                raise ValueError("Non-JSON number")

            result = json.loads(raw, parse_constant=invalid_constant)
        except (TypeError, ValueError):
            raise ServiceError("Model trả về JSON không hợp lệ. Vui lòng thử lại; kết quả chưa được sử dụng.") from None
        if not isinstance(result, dict):
            raise ServiceError("Model trả về sai cấu trúc JSON. Cần một đối tượng JSON, không phải danh sách hoặc văn bản.")
        return result

    def _record_usage(self, usage, input_field: str, output_field: str) -> None:
        if usage is None:
            return
        self.usage.append({
            "provider": self.provider,
            "model": self.model,
            "input_tokens": getattr(usage, input_field, None),
            "output_tokens": getattr(usage, output_field, None),
        })

    def close(self) -> None:
        if self._owns_client:
            self.client.close()
