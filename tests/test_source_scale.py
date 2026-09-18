"""Deterministic checks for 50-source retrieval and bounded model context."""

import copy
import json
import unittest
from unittest.mock import Mock

import httpx

from models.limits import MAX_SOURCES
from services.llm_service import ServiceError
from services.pipeline_service import (
    CROSSCHECK_EVIDENCE_MAX_CHARS, WRITER_EVIDENCE_MAX_CHARS, WRITER_MAX_CLAIMS,
    WRITER_CONFLICTS_MAX_CHARS, MODEL_INPUT_MAX_CHARS,
    PipelineService, _compact_claim, _json_size, _writer_evidence, _writer_conflicts,
)
from services.search_service import MAX_QUERIES, MAX_RESULTS_PER_QUERY, SearchService
from tests.test_pipeline import FakeLLM, FakeScraper, FakeSearch, LESSON, evaluation, raw_source
from tests.test_services import configuration


class SourceSearchScaleTests(unittest.TestCase):
    def run_fifty_source_search(self, languages):
        planner = Mock()
        planner.generate_json.return_value = {"queries": [
            {"query": f"Research angle {index} {language}", "language": language}
            for language in languages for index in range(5)
        ]}
        requests = []

        def respond(request):
            body = json.loads(request.content)
            requests.append(body)
            # A repeated URL across queries must not consume the source budget.
            return httpx.Response(200, json={"results": [
                {"url": "https://example.org/shared?utm_source=search", "content": "Not evidence"},
                *[{"url": f"https://example.org/{body['query'].replace(' ', '-')}/{index}"}
                  for index in range(body["max_results"] - 1)],
            ]})

        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            search = SearchService(planner, config=configuration(), client=client)
            queries = search.generate_queries("Research", [], "Learners", languages, max_sources=50)
            results = search.search_multiple(queries, max_sources=50)
        self.assertEqual(len(results), 50)
        self.assertEqual(len({source["url"] for source in results}), 50)
        self.assertLessEqual(len(requests), MAX_QUERIES)
        self.assertTrue(all(request["max_results"] == MAX_RESULTS_PER_QUERY for request in requests))
        self.assertFalse(any("content" in source for source in results))
        self.assertEqual(planner.generate_json.call_args.args[1]["max_sources"], 50)
        return results, queries

    def test_fifty_distinct_sources_are_reachable_in_one_language(self):
        results, queries = self.run_fifty_source_search(["en"])
        self.assertEqual(len(queries), 5)
        self.assertEqual({source["language"] for source in results}, {"en"})

    def test_fifty_sources_remain_balanced_across_languages(self):
        results, queries = self.run_fifty_source_search(["vi", "en"])
        self.assertEqual(len(queries), 6)
        self.assertEqual(sum(source["language"] == "vi" for source in results), 25)
        self.assertEqual(sum(source["language"] == "en" for source in results), 25)

    def test_insufficient_plan_is_repaired_before_searching_for_fifty(self):
        planner = Mock()
        planner.generate_json.side_effect = [
            {"queries": [{"query": "first angle", "language": "en"}]},
            {"queries": [{"query": f"additional angle {index}", "language": "en"} for index in range(4)]},
        ]
        queries = SearchService(planner, config=configuration()).generate_queries(
            "Research", [], "Learners", ["en"], max_sources=50)
        self.assertEqual(len(queries), 5)
        self.assertEqual(planner.generate_json.call_count, 2)

    def test_fifty_is_the_hard_service_boundary(self):
        client = Mock()
        search = SearchService(Mock(), config=configuration(), client=client)
        for limit in (0, MAX_SOURCES + 1, True, 50.5):
            with self.subTest(limit=limit):
                with self.assertRaises(ServiceError):
                    search.generate_queries("Research", [], "Learners", ["en"], max_sources=limit)
                with self.assertRaises(ServiceError):
                    search.search_multiple([{"query": "Research", "language": "en"}], max_sources=limit)
        client.post.assert_not_called()


class EvidenceScaleTests(unittest.TestCase):
    def test_conflicts_are_bounded_and_omissions_are_explicit(self):
        conflicts = [
            {"claim_ids": ["a1", "b1"], "source_ids": ["a", "b"],
             "description_vi": f"Khác biệt {index}: " + "Nội dung chi tiết. " * 80,
             "resolution_vi": "Giảng viên cần kiểm tra. " * 60}
            for index in range(30)
        ]
        conflicts.append({"claim_ids": ["a2", "b2"], "source_ids": ["a", "b"], "description_vi": "Không nằm trong tập luận điểm viết."})
        conflicts.append({"claim_ids": ["a1", "rejected_c1"], "source_ids": ["a", "rejected"], "description_vi": "Nguồn bị bỏ."})
        view = _writer_conflicts(conflicts, ["a", "b"], {"a1", "b1"})
        self.assertLessEqual(_json_size(view["conflicts"]), WRITER_CONFLICTS_MAX_CHARS)
        self.assertEqual(len(view["conflicts"]) + view["unrepresented_conflict_count"], 31)
        self.assertEqual(view["source_ids_with_unrepresented_conflicts"], ["a", "b"])
        self.assertTrue(all(set(item["claim_ids"]) <= {"a1", "b1"} for item in view["conflicts"]))

    def test_compact_view_preserves_context_and_does_not_mutate_claim(self):
        claim = {"claim_id": "claim_a", "source_id": "source_a", "source_title": "Original study",
                 "claim_text": "Navigation label " * 100,
                 "source_context": "This study does NOT establish causation. " + "Relevant original context. " * 60,
                 "snippet_quote": "Original quote", "snippet_translation_vi": "Bản dịch đầy đủ", "is_statistical": True}
        before = copy.deepcopy(claim)
        compact = _compact_claim(claim)
        self.assertEqual(compact["source_context"], claim["source_context"])
        self.assertTrue(compact["claim_text_is_excerpt"])
        self.assertEqual(claim, before)

    def test_maximum_context_lengths_still_cover_all_fifty_sources(self):
        claims = {}
        for index in range(50):
            for number in range(6):
                claim_id = f"src_{index:08}_c{number}"
                claims[claim_id] = {"claim_id": claim_id, "source_id": f"src_{index:08}",
                                    "claim_text": "đ" * 1600, "source_title": "Title " * 100,
                                    "snippet_quote": "q" * 1000,
                                    "source_context": "NOT " + "原" * 1696, "is_statistical": False}
        evidence = _writer_evidence(claims)
        self.assertEqual(len({claim["source_id"] for claim in evidence}), 50)
        self.assertLessEqual(_json_size(evidence), WRITER_EVIDENCE_MAX_CHARS)
        self.assertLessEqual(len(evidence), WRITER_MAX_CLAIMS)
        for compact in evidence:
            self.assertEqual(compact["source_context"], claims[compact["claim_id"]]["source_context"])

    def test_fifty_source_pipeline_retains_all_evidence_and_bounds_model_inputs(self):
        originals, evaluations = [], {}
        for index in range(50):
            quotes = [f"Finding {number} in source {index}: " + "Original research evidence and its limits. " * 15
                      for number in range(6)]
            raw = raw_source(f"src_{index:08}", "en", "\n\n".join(quotes))
            originals.append(raw)
            evaluations[raw.url] = evaluation("en", quotes[0], claims=[
                {"claim_text": f"Luận điểm {number}, nguồn {index}. " + "Phạm vi nghiên cứu được nêu rõ. " * 20,
                 "snippet_quote": quote, "snippet_translation_vi": "Diễn giải tiếng Việt đầy đủ.", "is_statistical": False}
                for number, quote in enumerate(quotes)
            ])
        llm, search = FakeLLM(evaluations), FakeSearch(originals)
        pipeline = PipelineService(llm=llm, search=search, scraper=FakeScraper(originals), admission=lambda req: None)
        req = {**LESSON, "max_sources": 50, "source_languages": ["en"]}
        session = {"req": req, **pipeline.research(req)}
        self.assertEqual(search.requested_max_sources, 50)
        self.assertEqual(len(session["dossier"]["sources"]), 50)
        all_claims = {claim["claim_id"]: claim for source in session["dossier"]["sources"] for claim in source["claims"]}
        self.assertEqual(len(all_claims), 300)
        cross_calls = [call for call in llm.calls if call["task"] == "cross_check"]
        self.assertGreater(len(cross_calls), 1)
        self.assertEqual({claim["claim_id"] for call in cross_calls for claim in call["claims"]}, set(all_claims))
        self.assertTrue(all(_json_size(call["claims"]) <= CROSSCHECK_EVIDENCE_MAX_CHARS for call in cross_calls))
        self.assertTrue(any("từng nhóm" in warning for warning in session["dossier"]["warnings"]))
        session["dossier"]["conflicts"] = [
            {"claim_ids": ["src_00000000_c1", "src_00000001_c1"],
             "source_ids": ["src_00000000", "src_00000001"],
             "description_vi": f"Khác biệt {index}: " + "Ngữ cảnh cần đối chiếu. " * 60,
             "resolution_vi": "Cần kiểm tra bản gốc. " * 60}
            for index in range(100)
        ]
        before = copy.deepcopy(session)
        approved = [source["source_id"] for source in session["dossier"]["sources"]]
        written = pipeline.review(session, approved)
        call = next(call for call in llm.calls if call["task"] == "write_script")
        self.assertEqual({claim["source_id"] for claim in call["approved_claims"]}, set(approved))
        self.assertLessEqual(_json_size(call["approved_claims"]), WRITER_EVIDENCE_MAX_CHARS)
        self.assertLessEqual(len(call["approved_claims"]), WRITER_MAX_CLAIMS)
        self.assertTrue(any("/300 luận điểm" in warning for warning in written["script"]["warnings"]))
        self.assertGreater(call["unrepresented_conflict_count"], 0)
        self.assertTrue(any("khác biệt giữa nguồn chưa" in warning for warning in written["script"]["warnings"]))
        self.assertEqual(len(written["dossier"]["conflicts"]), 100)
        for claim in call["approved_claims"]:
            self.assertEqual(claim["source_context"], all_claims[claim["claim_id"]]["source_context"])
        for audit in (call for call in llm.calls if call["task"] == "audit_script"):
            self.assertLessEqual(_json_size({"lines": audit["lines"], "evidence": audit["evidence"]}), WRITER_EVIDENCE_MAX_CHARS)
        self.assertEqual(session, before)
        self.assertEqual(sum(len(source["claims"]) for source in written["dossier"]["sources"]), 300)
        self.assertTrue(all(not line["is_unverified"] for scene in written["script"]["scenes"] for line in scene["lines"]))
        self.assertTrue(all(len(call["system"]) + _json_size({key: value for key, value in call.items() if key != "system"})
                            <= MODEL_INPUT_MAX_CHARS for call in llm.calls))


if __name__ == "__main__":
    unittest.main()
