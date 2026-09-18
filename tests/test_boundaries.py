"""Regression cases for malformed model output and provenance boundaries."""
import copy
import unittest

from tests.test_pipeline import EN_QUOTE, FR_QUOTE, LESSON, FakeLLM, FakeSearch, FakeScraper, evaluation, raw_source
from services.pipeline_service import PipelineService


class OutputBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.sources = [raw_source("src_en", "en", EN_QUOTE), raw_source("src_fr", "fr", FR_QUOTE)]
        self.llm = FakeLLM({self.sources[0].url: evaluation("en", EN_QUOTE),
                            self.sources[1].url: evaluation("fr", FR_QUOTE)})
        self.scraper = FakeScraper(self.sources)
        self.pipeline = PipelineService(llm=self.llm, search=FakeSearch(self.sources), scraper=self.scraper,
                                        admission=lambda req: None)

    def research_session(self):
        return {"req": copy.deepcopy(LESSON), **self.pipeline.research(copy.deepcopy(LESSON))}

    def written_session(self):
        session = self.research_session()
        session.update(self.pipeline.review(session, ["src_en", "src_fr"]))
        return session

    def task_calls(self, task):
        return [call for call in self.llm.calls if call["task"] == task]

    def test_null_nested_source_output_is_not_saved_as_evidence(self):
        self.llm.evaluations[self.sources[0].url] = evaluation('en', EN_QUOTE, claims=[None])
        result = self.pipeline.evaluate_source(self.sources[0].model_dump(mode='json'), LESSON)
        self.assertEqual(result['claims'], [])
        self.assertTrue(any('không hợp lệ' in warning for warning in result['warnings']))

    def test_invalid_cross_check_is_reported_instead_of_claiming_no_conflict(self):
        self.llm.handlers['cross_check'] = {'conflicts': [None]}
        session = self.research_session()
        self.assertEqual(session['dossier']['conflicts'], [])
        self.assertTrue(any('Chưa hoàn tất đối chiếu' in warning for warning in session['dossier']['warnings']))

    def test_rejected_source_conflicts_never_reach_writer(self):
        self.llm.handlers['cross_check'] = {'conflicts': [{'claim_ids': ['src_en_c1', 'src_fr_c1'], 'description_vi': 'Khác biệt.', 'resolution_vi': 'Kiểm tra.'}]}
        session = self.research_session()
        self.pipeline.review(session, ['src_en'])
        self.assertEqual(self.task_calls('write_script')[-1]['conflicts'], [])

    def test_auditor_receives_real_context_around_quote(self):
        prefix = 'IMPORTANT: The following finding does not apply to all settings. '
        self.sources[0].raw_markdown = prefix + self.sources[0].raw_markdown
        self.scraper.sources[self.sources[0].url] = self.sources[0]
        session = self.research_session()
        claim = session['dossier']['sources'][0]['claims'][0]
        self.assertIn(prefix, claim['source_context'])
        self.pipeline.review(session, ['src_en'])
        evidence = self.task_calls('audit_script')[-1]['evidence'][0]
        self.assertEqual(evidence['source_context'], claim['source_context'])

    def test_bad_patch_does_not_mutate_original_session(self):
        session = self.written_session()
        before = copy.deepcopy(session)
        self.llm.handlers['patch_script'] = {'lines': None}
        with self.assertRaisesRegex(ValueError, 'không hợp lệ'):
            self.pipeline.patch(session, ['src_en'])
        self.assertEqual(session, before)


if __name__ == '__main__':
    unittest.main()
