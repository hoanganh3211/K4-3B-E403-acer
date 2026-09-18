import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx

from services.llm_service import LLMService, ServiceError, api_key_configured
from services.search_service import LANGUAGES, SearchService, normalized_url


def configuration(**overrides):
    fields = dict(llm_provider="openai", openai_model="test-model", google_model="test-gemini",
                  openai_api_key="", google_api_key="", tavily_api_key="test-tavily-secret",
                  max_tokens=2048, llm_timeout_seconds=10, search_timeout_seconds=5)
    return SimpleNamespace(**(fields | overrides))


def openai_response(content='{"result": "tiếng Việt"}', finish="stop", refusal=None):
    return SimpleNamespace(
        choices=[SimpleNamespace(finish_reason=finish, message=SimpleNamespace(content=content, refusal=refusal))],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20),
    )


class LLMServiceTests(unittest.TestCase):
    def test_openai_json_and_real_usage(self):
        client = Mock()
        client.chat.completions.create.return_value = openai_response()
        llm = LLMService(config=configuration(), client=client)
        self.assertEqual(llm.generate_json("Translate", {"topic": "cây xanh"}), {"result": "tiếng Việt"})
        request = client.chat.completions.create.call_args.kwargs
        self.assertEqual(request["response_format"], {"type": "json_object"})
        self.assertEqual(request["max_completion_tokens"], 2048)
        self.assertIn("JSON", request["messages"][0]["content"])
        self.assertEqual(json.loads(request["messages"][1]["content"]), {"topic": "cây xanh"})
        self.assertEqual(llm.usage, [{"provider": "openai", "model": "test-model", "input_tokens": 100, "output_tokens": 20}])

    def test_invalid_json_never_becomes_fallback_content(self):
        for content in ('{"unfinished":', '[]', 'null', '```json\n{}\n```', '{"bad": NaN}', None):
            with self.subTest(content=content):
                client = Mock()
                client.chat.completions.create.return_value = openai_response(content)
                with self.assertRaises(ServiceError):
                    LLMService(config=configuration(), client=client).generate_json("Task", {})

    def test_truncation_and_refusal_reject_even_parseable_output(self):
        for response in (openai_response("{}", "length"), openai_response("{}", refusal="private refusal")):
            client = Mock()
            client.chat.completions.create.return_value = response
            with self.assertRaises(ServiceError):
                LLMService(config=configuration(), client=client).generate_json("Task", {})

    def test_provider_error_is_actionable_without_leaking_exception(self):
        client = Mock()
        error = RuntimeError("sk-private-key and full prompt payload")
        error.status_code = 401
        client.chat.completions.create.side_effect = error
        with self.assertRaises(ServiceError) as caught:
            LLMService(config=configuration(), client=client).generate_json("Task", {})
        self.assertIn("xác thực", str(caught.exception))
        self.assertNotIn("sk-private-key", str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)

    def test_missing_key_rejected_before_network(self):
        with self.assertRaisesRegex(ServiceError, "OPENAI_API_KEY"):
            LLMService(config=configuration())
        with self.assertRaisesRegex(ServiceError, "GOOGLE_API_KEY"):
            LLMService(config=configuration(llm_provider="google"))
        with self.assertRaisesRegex(ServiceError, "LLM_PROVIDER"):
            LLMService(config=configuration(llm_provider="other"))

    def test_example_credentials_are_rejected_before_client_creation(self):
        with patch("openai.OpenAI") as constructor:
            for value in ("your_openai_api_key", "sk-your-key-here", "replace_me", "   "):
                with self.subTest(value=value), self.assertRaisesRegex(ServiceError, "giá trị mẫu"):
                    LLMService(config=configuration(openai_api_key=value))
            constructor.assert_not_called()
        self.assertFalse(api_key_configured("tvly-your-key"))
        self.assertTrue(api_key_configured("sk-proj-an-opaque-realistic-value"))

    def test_google_json_config_and_usage(self):
        client = Mock()
        client.models.generate_content.return_value = SimpleNamespace(
            text='{"summary_vi": "Nội dung tiếng Việt"}', candidates=[SimpleNamespace(finish_reason="STOP")],
            usage_metadata=SimpleNamespace(prompt_token_count=80, candidates_token_count=30),
        )
        llm = LLMService(config=configuration(llm_provider="google"), client=client)
        self.assertEqual(llm.generate_json("Task", {})["summary_vi"], "Nội dung tiếng Việt")
        self.assertEqual(client.models.generate_content.call_args.kwargs["config"]["response_mime_type"], "application/json")
        self.assertEqual(llm.usage[0]["output_tokens"], 30)
        client.models.generate_content.return_value.candidates[0].finish_reason = "MAX_TOKENS"
        with self.assertRaisesRegex(ServiceError, "giới hạn token"):
            llm.generate_json("Task", {})


class SearchServiceTests(unittest.TestCase):
    def test_query_limit_still_covers_all_eight_languages(self):
        llm = Mock()
        llm.generate_json.return_value = {"queries": [
            {"query": f"Research {language} {index}", "language": language}
            for language in LANGUAGES for index in range(2)
        ]}
        queries = SearchService(llm, config=configuration()).generate_queries("Topic", [], "Learners", list(LANGUAGES))
        self.assertEqual(len(queries), 8)
        self.assertEqual([query["language"] for query in queries], list(LANGUAGES))

    def test_missing_language_is_repaired_with_translated_query(self):
        llm = Mock()
        llm.generate_json.side_effect = [
            {"queries": [{"query": "quang hợp", "language": "vi"}, {"language": {}, "query": "invalid"}]},
            {"queries": [{"query": "photosynthesis primary research", "language": "en"}]},
        ]
        queries = SearchService(llm, config=configuration()).generate_queries("Quang hợp", [], "Học sinh", ["vi", "en"])
        self.assertEqual(queries[-1]["query"], "photosynthesis primary research")
        repair_payload = llm.generate_json.call_args.args[1]
        self.assertEqual([entry["code"] for entry in repair_payload["source_languages"]], ["en"])

    def test_irreparable_query_response_fails_after_bounded_attempts(self):
        llm = Mock()
        llm.generate_json.return_value = {"queries": "wrong type"}
        with self.assertRaisesRegex(ServiceError, "đủ ngôn ngữ"):
            SearchService(llm, config=configuration()).generate_queries("Topic", [], "Learners", ["ja"])
        self.assertEqual(llm.generate_json.call_count, 2)

    def test_unsupported_and_empty_languages_fail(self):
        for languages in ([], ["xx"], [{"vi": 1}], "en"):
            with self.subTest(languages=languages), self.assertRaises(ServiceError):
                SearchService(Mock(), config=configuration()).generate_queries("Topic", [], "Learners", languages)

    def test_placeholder_search_key_is_rejected_before_network(self):
        client = Mock()
        with self.assertRaisesRegex(ServiceError, "giá trị mẫu"):
            SearchService(config=configuration(tavily_api_key="your_tavily_api_key"), client=client).search_multiple(
                [{"query": "Q", "language": "en"}]
            )
        client.post.assert_not_called()

    def test_balanced_sources_deduplicate_tracking_and_never_use_snippets(self):
        requests = []

        def handler(request):
            body = json.loads(request.content)
            requests.append(body)
            if body["language"] == "vi":
                results = [
                    {"url": "https://www.example.org/paper/?utm_source=search#intro", "title": "VN", "content": "not evidence"},
                    {"url": "https://example.org/vietnamese"},
                ]
            else:
                results = [{"url": "http://example.org/paper"}, {"url": "https://university.edu/study", "title": "EN"}]
            return httpx.Response(200, json={"results": results})

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            search = SearchService(config=configuration(), client=client)
            result = search.search_multiple([
                {"query": "nghiên cứu", "language": "vi"}, {"query": "research", "language": "en"},
            ], max_sources=3)
        self.assertEqual(len(result), 3)
        self.assertEqual([item["language"] for item in result], ["vi", "en", "vi"])
        self.assertEqual(result[1]["url"], "https://university.edu/study")
        self.assertFalse(any("content" in item or "raw_content" in item for item in result))
        self.assertTrue(all(not body["include_answer"] and not body["include_raw_content"] for body in requests))
        self.assertTrue(all(body["filter_by_language"] for body in requests))
        self.assertEqual(len(search.query_log), 2)

    def test_every_language_is_searched_before_limiting_results(self):
        calls = []

        def handler(request):
            body = json.loads(request.content)
            calls.append(body["language"])
            return httpx.Response(200, json={"results": [{"url": f"https://example.com/{body['language']}"}]})

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            search = SearchService(config=configuration(), client=client)
            result = search.search_multiple([{"query": lang, "language": lang} for lang in ("vi", "en", "ja")], 2)
        self.assertEqual(set(calls), {"vi", "en", "ja"})
        self.assertEqual(len(result), 2)
        self.assertTrue(search.warnings)

    def test_partial_failure_preserves_success_and_reports_gap(self):
        def handler(request):
            if json.loads(request.content)["language"] == "vi":
                raise httpx.ReadTimeout("private request data", request=request)
            return httpx.Response(200, json={"results": [{"url": "https://example.org/research"}]})

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            search = SearchService(config=configuration(), client=client)
            result = search.search_multiple([{"query": "A", "language": "vi"}, {"query": "B", "language": "en"}])
        self.assertEqual(len(result), 1)
        self.assertEqual([item["status"] for item in search.query_log], ["error", "ok"])
        self.assertIn("quá thời gian", " ".join(search.warnings))
        self.assertNotIn("private request data", " ".join(search.warnings))

    def test_all_failures_return_sanitized_error(self):
        with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(
            401, json={"error": "test-tavily-secret"}
        ))) as client:
            search = SearchService(config=configuration(), client=client)
            with self.assertRaises(ServiceError) as caught:
                search.search_multiple([{"query": "Q", "language": "en"}])
        self.assertIn("TAVILY_API_KEY", str(caught.exception))
        self.assertNotIn("test-tavily-secret", str(caught.exception))

    def test_normalization_preserves_meaningful_query_values(self):
        self.assertEqual(normalized_url("https://WWW.example.org/a/?utm_medium=x&id=2#top"),
                         normalized_url("http://example.org/a?id=2"))
        self.assertNotEqual(normalized_url("https://example.org/a?id=1"), normalized_url("https://example.org/a?id=2"))
        self.assertEqual(normalized_url("javascript:alert(1)"), "")
        self.assertEqual(normalized_url("https://user:password@example.org/a"), "")


if __name__ == "__main__":
    unittest.main()
