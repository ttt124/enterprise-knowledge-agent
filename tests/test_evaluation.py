"""Keep the evaluator honest: expected answers must not become observations."""
import copy
import json
from pathlib import Path
import re
import sys
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from evaluate import check_mock_output, check_output, prepare_documents

try:
    from .test_tools import DOCUMENTS
except ImportError:
    from test_tools import DOCUMENTS


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.quote = DOCUMENTS[0]["content"].split("\n\n")[0]
        self.case = {"expected": {"status": ["completed"], "citation_doc_ids": ["D001"], "answer_regex": "7|七"}}
        self.result = {"status": "completed", "answer": "应在7天内归还。", "tool_calls": 1,
                       "citations": [{"doc_id": "D001", "passage_id": "D001#p1", "quote": self.quote}],
                       "trace": [{"tool": "read_document", "arguments": {"doc_id": "D001"},
                                  "observation": {"ok": True, "doc_id": "D001", "passages": [
                                      {"passage_id": "D001#p1", "text": self.quote}]}}]}

    def checks(self, result):
        return {item["check"]: item["passed"] for item in check_output(result, self.case, DOCUMENTS)}

    def test_valid_current_read_quote_passes(self):
        self.assertTrue(all(self.checks(self.result).values()))

    def test_expected_number_does_not_mask_missing_actual_number(self):
        self.result["answer"] = "请向管理员咨询。"
        self.assertFalse(self.checks(self.result)["answer_contains_expected_fact"])

    def test_source_quote_without_read_observation_fails(self):
        self.result["trace"] = []
        self.assertFalse(self.checks(self.result)["citation_1_was_read"])

    def test_fabricated_read_quote_still_fails_source_check(self):
        self.result["citations"][0]["quote"] = "应在99天内归还。"
        self.result["trace"][0]["observation"]["passages"][0]["text"] = "应在99天内归还。"
        self.assertFalse(self.checks(self.result)["citation_1_verbatim"])

    def test_mutation_keeps_default_documents_untouched(self):
        original = copy.deepcopy(DOCUMENTS)
        snapshot = prepare_documents(DOCUMENTS, {"mutation": {
            "type": "replace", "doc_id": "D001", "old": "7天", "new": "10天"}})
        self.assertIn("10天", snapshot[0]["content"])
        self.assertEqual(DOCUMENTS, original)
        appended = prepare_documents(DOCUMENTS, {"mutation": {"type": "append_conflict", "doc_id": "D009"}})
        self.assertEqual(len(appended), len(original) + 1)
        self.assertEqual(DOCUMENTS, original)

    def test_mock_validates_flow_without_grading_business_expectations(self):
        self.result.update(status="incomplete", answer="离线模拟不提供业务结论。", citations=[])
        self.result["trace"][0]["event"] = "tool_call"
        self.result["trace"].append({"event": "final", "status": "incomplete"})
        checks = check_mock_output(self.result, self.case, DOCUMENTS)
        self.assertTrue(all(item["passed"] for item in checks))
        self.assertNotIn("answer_contains_expected_fact", {item["check"] for item in checks})
        self.assertNotIn("cites_D001", {item["check"] for item in checks})

    def test_mock_failure_case_requires_actual_failure_observation(self):
        self.result.update(status="incomplete", citations=[])
        self.case["expected"]["tool_failure_observed"] = True
        checks = {item["check"]: item["passed"] for item in check_mock_output(self.result, self.case, DOCUMENTS)}
        self.assertFalse(checks["tool_failure_observed"])

    def test_conflict_advice_patterns_allow_confirmation_and_reject_execution_advice(self):
        cases = {case["id"]: case for case in json.loads(
            (PROJECT_ROOT / "data" / "evaluation_cases.json").read_text(encoding="utf-8"))}
        samples = {
            "T02": (["建议按较严格15天执行。", "建议先按十五天提交。"],
                    ["建议向财务确认15天与30天的适用条件。", "建议确认应按15天还是30天提交。"]),
            "T09": (["建议按3天归还。", "先按三天执行。"],
                    ["建议向管理员确认3天与7天的适用条件。", "建议确认应按3天还是7天归还。"]),
        }
        for case_id, (forbidden, allowed) in samples.items():
            pattern = cases[case_id]["expected"]["forbidden_answer_regex"]
            for answer in forbidden:
                with self.subTest(case=case_id, forbidden=answer):
                    self.assertIsNotNone(re.search(pattern, answer))
            for answer in allowed:
                with self.subTest(case=case_id, allowed=answer):
                    self.assertIsNone(re.search(pattern, answer))


if __name__ == "__main__":
    unittest.main()
