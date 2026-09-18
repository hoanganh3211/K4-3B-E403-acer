"""Gemini admission adapter contracts, using SDK mocks only (no live calls)."""

import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from google.genai import types

import services.moderation_service as moderation
from services.content_policy import ContentPolicyError
from services.llm_service import ServiceError


LESSON = {"topic": "Giới thiệu trí tuệ nhân tạo", "target_audience": "Sinh viên",
          "objectives": ["Giải thích các khái niệm cơ bản"], "teaching_style": "Rõ ràng, có ví dụ"}
ALLOW = {"decision": "allow", "subject": "general_education", "intent": "educational", "field": "lesson"}


class GeminiModerationTests(unittest.TestCase):
    def setUp(self):
        self.config = SimpleNamespace(
            google_api_key="test-private-gemini-key", google_model="gemini-test-model", moderation_model="",
            llm_provider="openai", openai_api_key="different-key", openai_model="research-model",
        )
        self.client = Mock()
        self.client.models.generate_content.return_value = SimpleNamespace(
            text=json.dumps(ALLOW), candidates=[SimpleNamespace(finish_reason=types.FinishReason.STOP)])
        patcher = patch("google.genai.Client", return_value=self.client)
        self.factory = patcher.start()
        self.addCleanup(patcher.stop)
        self.evaluator = moderation.GeminiModerationEvaluator(config=self.config)

    def test_short_check_uses_gemini_without_tools_retries_or_research_provider(self):
        self.factory.assert_not_called()
        result = self.evaluator("Classify the lesson; return the required JSON object.", LESSON)
        self.assertEqual(result, ALLOW)
        self.factory.assert_called_once()
        client_options = self.factory.call_args.kwargs
        self.assertEqual(client_options["api_key"], self.config.google_api_key)
        self.assertFalse(client_options["vertexai"])
        self.assertEqual(client_options["http_options"].timeout, 20_000)
        self.assertEqual(client_options["http_options"].retry_options.attempts, 1)
        self.client.models.generate_content.assert_called_once()
        request = self.client.models.generate_content.call_args.kwargs
        self.assertEqual(request["model"], self.config.google_model)
        self.assertEqual(json.loads(request["contents"]), LESSON)
        generation = request["config"]
        self.assertEqual(generation.temperature, 0)
        self.assertEqual(generation.candidate_count, 1)
        self.assertGreaterEqual(generation.max_output_tokens, 512)
        self.assertLessEqual(generation.max_output_tokens, 1024)
        self.assertEqual(generation.response_mime_type, "application/json")
        self.assertEqual(generation.response_json_schema, moderation.ADMISSION_RESPONSE_SCHEMA)
        self.assertEqual(generation.tools, [])
        self.assertTrue(generation.automatic_function_calling.disable)
        self.assertIsNone(generation.tool_config)
        self.assertIsNone(generation.cached_content)
        self.client.close.assert_called_once()

    def test_optional_moderation_model_overrides_google_research_model(self):
        self.config.moderation_model = "  gemini-moderation-test  "
        self.evaluator("Return JSON.", LESSON)
        self.assertEqual(self.client.models.generate_content.call_args.kwargs["model"], "gemini-moderation-test")
        self.assertEqual(self.config.google_model, "gemini-test-model")

    def test_missing_or_example_credentials_fail_before_sdk_client_creation(self):
        for key in ("", " ", "replace_me", "your_google_api_key"):
            with self.subTest(key=key):
                self.config.google_api_key = key
                with self.assertRaises(ServiceError):
                    self.evaluator("Return JSON.", LESSON)
                self.factory.assert_not_called()
        self.config.google_api_key = "test-private-gemini-key"
        self.config.google_model = ""
        with self.assertRaises(ServiceError):
            self.evaluator("Return JSON.", LESSON)
        self.factory.assert_not_called()

    def test_provider_failure_is_sanitized_and_never_retried(self):
        for failure in (TimeoutError("secret-key in timed out request"),
                        RuntimeError("https://provider.example/?key=test-private-gemini-key payload=private-input")):
            with self.subTest(failure=type(failure).__name__):
                self.factory.reset_mock()
                self.client.reset_mock()
                self.client.models.generate_content.side_effect = failure
                with self.assertRaises(ServiceError) as raised:
                    self.evaluator("Return JSON.", LESSON)
                message = str(raised.exception)
                self.assertNotIn("secret-key", message)
                self.assertNotIn("test-private-gemini-key", message)
                self.assertNotIn("private-input", message)
                self.assertNotIn("provider.example", message)
                self.factory.assert_called_once()
                self.client.models.generate_content.assert_called_once()
                self.client.close.assert_called_once()

    def test_constructor_failure_is_sanitized_without_attempting_generation(self):
        self.factory.side_effect = RuntimeError("test-private-gemini-key constructor failure")
        with self.assertRaises(ServiceError) as raised:
            self.evaluator("Return JSON.", LESSON)
        self.assertNotIn("test-private-gemini-key", str(raised.exception))
        self.factory.assert_called_once()
        self.client.models.generate_content.assert_not_called()

    def test_non_json_or_ambiguous_json_is_rejected_and_client_closed(self):
        for raw in ("", "not JSON", "```json\n{}\n```", "[]", "null", '{"decision": NaN}',
                    '{"decision":"block","decision":"allow"}', '{"decision":"allow"',
                    "x" * (moderation.MODERATION_MAX_RESPONSE_CHARS + 1)):
            with self.subTest(raw=raw[:60]):
                self.client.reset_mock()
                self.client.models.generate_content.return_value = SimpleNamespace(
                    text=raw, candidates=[SimpleNamespace(finish_reason="STOP")])
                with self.assertRaises(ServiceError):
                    self.evaluator("Return JSON.", LESSON)
                self.client.models.generate_content.assert_called_once()
                self.client.close.assert_called_once()

    def test_non_completed_or_missing_candidates_cannot_admit_a_lesson(self):
        candidates = [[], None, [SimpleNamespace(finish_reason="MAX_TOKENS")],
                      [SimpleNamespace(finish_reason="SAFETY")], [SimpleNamespace(finish_reason=None)],
                      [SimpleNamespace(finish_reason="STOP"), SimpleNamespace(finish_reason="STOP")]]
        for values in candidates:
            with self.subTest(candidates=values):
                self.client.reset_mock()
                self.client.models.generate_content.return_value = SimpleNamespace(text=json.dumps(ALLOW), candidates=values)
                with self.assertRaises(ServiceError):
                    self.evaluator("Return JSON.", LESSON)
                self.client.close.assert_called_once()

    def test_invalid_or_oversized_input_never_reaches_gemini(self):
        for payload in ({"topic": float("nan")}, {"topic": object()},
                        {"topic": "x" * (moderation.MODERATION_MAX_INPUT_CHARS + 1)}):
            with self.subTest(value_type=type(payload["topic"]).__name__):
                with self.assertRaises(ServiceError):
                    self.evaluator("Return JSON.", payload)
                self.factory.assert_not_called()
        with self.assertRaises(ServiceError):
            self.evaluator("", LESSON)
        self.factory.assert_not_called()

    def test_local_rejection_happens_before_admission_singleton_or_provider(self):
        with patch.object(moderation, "_admission_service", None), patch.object(
            moderation, "AdmissionPolicyService", side_effect=AssertionError("Must quick-reject before semantic service")
        ) as admission:
            with self.assertRaises(ContentPolicyError):
                moderation.require_research_admission({**LESSON, "topic": "Hướng dẫn đánh bạc trên mạng kiếm tiền"})
            admission.assert_not_called()
        self.factory.assert_not_called()

    def test_remaining_lessons_always_use_singleton_admission_service(self):
        service = Mock()
        decision = object()
        service.require.return_value = decision
        with patch.object(moderation, "_admission_service", None), patch.object(
            moderation, "AdmissionPolicyService", return_value=service
        ) as admission:
            self.assertIs(moderation.require_research_admission(LESSON), decision)
            self.assertIs(moderation.require_research_admission(LESSON), decision)
            admission.assert_called_once()
            self.assertEqual(service.require.call_count, 2)
            service.require.assert_called_with(LESSON)
        self.factory.assert_not_called()

    def test_missing_gemini_configuration_fails_closed_in_full_admission_wrapper(self):
        self.config.google_api_key = ""
        with patch.object(moderation, "_admission_service", None), patch.object(moderation, "settings", self.config):
            with self.assertRaises(ContentPolicyError) as raised:
                moderation.require_research_admission(LESSON)
            self.assertEqual(raised.exception.category, "admission_unavailable")
        self.factory.assert_not_called()

    def test_full_wrapper_uses_gemini_then_cache_and_rechecks_changed_objectives(self):
        with patch.object(moderation, "_admission_service", None), patch.object(moderation, "settings", self.config):
            first = moderation.require_research_admission(LESSON)
            cached = moderation.require_research_admission(dict(LESSON))
            self.assertEqual(first.decision, "allow")
            self.assertFalse(first.cached)
            self.assertTrue(cached.cached)
            self.client.models.generate_content.assert_called_once()
            changed = moderation.require_research_admission({**LESSON, "objectives": ["So sánh học có giám sát và không giám sát"]})
            self.assertFalse(changed.cached)
            self.assertNotEqual(changed.input_digest, first.input_digest)
            self.assertEqual(self.client.models.generate_content.call_count, 2)
            self.assertEqual(self.client.close.call_count, 2)


if __name__ == "__main__":
    unittest.main()
