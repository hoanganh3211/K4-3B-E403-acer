"""Check evaluator accounting before running any golden/model cases."""
import unittest
from eval.harness import score_case, summarize


class HarnessTests(unittest.TestCase):
    def setUp(self):
        self.case = {"id": "fixture", "group": "ordinary", "runner": "contract",
                     "expected": {"checks": ["required_a", "required_b"]}}

    def test_missing_or_truthy_non_boolean_checks_fail(self):
        for checks in ({"required_a": True}, {"required_a": True, "required_b": 1}, {}):
            self.assertFalse(score_case(self.case, {"checks": checks})["passed"])

    def test_all_checks_and_no_error_are_required(self):
        observed = {"checks": {"required_a": True, "required_b": True}}
        self.assertTrue(score_case(self.case, observed)["passed"])
        self.assertFalse(score_case(self.case, {**observed, "error": {"type": "Timeout"}})["passed"])

    def test_incomplete_denominator_is_not_shrunk(self):
        quality = {"pass_percentage": 90, "limited_min_percentage": 80,
                   "hard_conditions": [], "scope": {"full_web": False}, "ship_requires": ["full_web"]}
        outcome = summarize([self.case], [], quality)
        self.assertEqual(outcome["total"], 1)
        self.assertEqual(outcome["passed"], 0)
        self.assertEqual(outcome["status"], "Hold")

    def test_fixture_only_green_does_not_become_ship(self):
        quality = {"pass_percentage": 90, "limited_min_percentage": 80,
                   "hard_conditions": [], "scope": {"full_web": False}, "ship_requires": ["full_web"]}
        row = score_case(self.case, {"checks": {"required_a": True, "required_b": True}})
        outcome = summarize([self.case], [row], quality)
        self.assertTrue(outcome["quality_bar_met"])
        self.assertEqual(outcome["status"], "Limited")

    def test_missing_check_is_incomplete_execution(self):
        quality = {"pass_percentage": 90, "limited_min_percentage": 80,
                   "hard_conditions": [], "scope": {}, "ship_requires": []}
        row = score_case(self.case, {"checks": {"required_a": True}})
        outcome = summarize([self.case], [row], quality)
        self.assertFalse(outcome["complete"])
        self.assertEqual(outcome["hard_violations"][0]["condition"], "HC-INTEGRITY")

    def test_hard_failure_overrides_high_pass_rate(self):
        quality = {"pass_percentage": 90, "limited_min_percentage": 80,
                   "hard_conditions": [{"id": "HC", "references": [{"case_id": "fixture", "check": "safety"}]}],
                   "scope": {"full_web": True}, "ship_requires": ["full_web"]}
        row = score_case(self.case, {"checks": {"required_a": True, "required_b": True, "safety": False}})
        outcome = summarize([self.case], [row], quality)
        self.assertEqual(outcome["pass_percentage"], 100)
        self.assertFalse(outcome["quality_bar_met"])
        self.assertEqual(outcome["status"], "Hold")
