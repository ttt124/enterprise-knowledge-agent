"""Scripted model tests validate orchestration, never live-model intelligence."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from knowledge_agent.agent import run_agent
from knowledge_agent.tools import KnowledgeStore, Toolbox

try:
    from .test_tools import DOCUMENTS
except ImportError:
    from test_tools import DOCUMENTS


def tool_call(name, **arguments):
    return {"role": "assistant", "content": None, "tool_calls": [
        {"id": f"call_{name}", "type": "function",
         "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)}}]}


def final_message(answer="", citations=None, status="completed", reason="依据已读原文", gaps=None):
    return {"role": "assistant", "content": json.dumps({
        "answer": answer, "citations": citations or [], "gaps": gaps or [],
        "status": status, "reason": reason,
    }, ensure_ascii=False)}


class ScriptedModel:
    mode = "mock"
    name = "scripted-flow-test"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete(self, messages, tools):
        self.calls.append(copy.deepcopy(messages))
        if not self.responses:
            return final_message(status="incomplete", reason="测试响应序列已用尽", gaps=["缺少有效答案"])
        response = self.responses.pop(0)
        return response(messages, tools) if callable(response) else copy.deepcopy(response)


class LoopModel:
    mode = "mock"
    name = "loop-budget-test"

    def complete(self, messages, tools):
        return tool_call("read_document", doc_id="D001", reason="验证失败调用也受预算限制")


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="knowledge-agent-test-")
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "documents.json"
        self.write_documents(DOCUMENTS)
        self.toolbox = Toolbox(KnowledgeStore(self.path))

    def write_documents(self, documents):
        self.path.write_text(json.dumps(documents, ensure_ascii=False), encoding="utf-8")

    def search_and_read(self):
        return [tool_call("search_documents", query="设备借用", reason="查找制度"),
                tool_call("read_document", doc_id="D001", reason="核对期限原文")]

    def citation(self, **overrides):
        citation = {"doc_id": "D001", "passage_id": "D001#p1",
                    "quote": "员工借用公司设备后，应在7天内归还。"}
        citation.update(overrides)
        return citation

    def test_valid_read_quote_is_accepted_and_trace_has_observations(self):
        model = ScriptedModel(self.search_and_read() + [final_message("应在7天内归还。", [self.citation()])])
        result = run_agent("设备借用期限？", model=model, toolbox=self.toolbox)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["citations"], [self.citation()])
        self.assertEqual(result["tool_calls"], 2)
        calls = [event for event in result["trace"] if event.get("tool") in {"search_documents", "read_document"}]
        self.assertEqual(len(calls), 2)
        for event in calls:
            for field in ("step", "arguments", "rationale", "observation", "next_action"):
                self.assertIn(field, event)
        self.assertTrue(any(event.get("tool") not in {"search_documents", "read_document"}
                            for event in result["trace"]), "Trace must include terminal event")

    def test_search_snippet_cannot_be_cited_without_reading_document(self):
        model = ScriptedModel([self.search_and_read()[0], final_message("7天。", [self.citation()])])
        result = run_agent("设备借用期限？", model=model, toolbox=self.toolbox)
        self.assertNotEqual(result["status"], "completed")
        self.assertEqual(result["citations"], [])

    def test_quote_must_be_verbatim_and_point_to_the_read_passage(self):
        invalid_citations = [self.citation(quote="员工应在10天内归还设备。"),
                             self.citation(passage_id="D001#p99"),
                             self.citation(doc_id="D002"), self.citation(quote="")]
        for citation in invalid_citations:
            with self.subTest(citation=citation):
                model = ScriptedModel(self.search_and_read() + [final_message("设备可以借10天。", [citation])])
                result = run_agent("设备借用期限？", model=model, toolbox=self.toolbox)
                self.assertNotEqual(result["status"], "completed")
                self.assertEqual(result["citations"], [])

    def test_failed_tool_calls_consume_budget(self):
        toolbox = Toolbox(KnowledgeStore(self.path), failures={"read_document": -1})
        result = run_agent("设备借用期限？", model=LoopModel(), toolbox=toolbox,
                           max_tool_calls=3, max_model_turns=10)
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["tool_calls"], 3)
        failed = [event for event in result["trace"] if event.get("tool") == "read_document"
                  and isinstance(event.get("observation"), dict) and event["observation"].get("ok") is False]
        self.assertEqual(len(failed), 3)
        self.assertEqual(result["citations"], [])

    def test_model_can_observe_failure_and_stop_without_using_all_budget(self):
        toolbox = Toolbox(KnowledgeStore(self.path), failures={"read_document": -1})

        def respond_to_failure(messages, tools):
            observations = [json.loads(message["content"]) for message in messages if message.get("role") == "tool"]
            self.assertTrue(observations, "Model must receive the tool observation")
            self.assertIs(observations[-1]["ok"], False)
            self.assertTrue(observations[-1].get("error"))
            return final_message("读取资料失败，暂时无法给出期限。", status="incomplete",
                                 reason="工具故障", gaps=["尚未读取原文"])

        model = ScriptedModel([tool_call("read_document", doc_id="D001", reason="读取制度"), respond_to_failure])
        result = run_agent("设备借用期限？", model=model, toolbox=toolbox, max_tool_calls=8)
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["tool_calls"], 1)
        self.assertEqual(len(model.calls), 2)

    def test_model_turn_limit_prevents_tool_free_endless_empty_response(self):
        model = ScriptedModel([{"role": "assistant", "content": ""}] * 10)
        result = run_agent("设备借用期限？", model=model, toolbox=self.toolbox, max_model_turns=3)
        self.assertEqual(result["status"], "incomplete")
        self.assertLessEqual(result["model_turns"], 3)
        self.assertEqual(result["tool_calls"], 0)

    def test_one_tool_budget_cannot_complete_from_search_snippets(self):
        model = ScriptedModel(self.search_and_read() + [final_message("7天。", [self.citation()])])
        result = run_agent("设备借用期限？", model=model, toolbox=self.toolbox, max_tool_calls=1)
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["tool_calls"], 1)
        self.assertEqual(result["citations"], [])

    def test_exact_tool_budget_still_allows_model_final_answer(self):
        model = ScriptedModel(self.search_and_read() + [final_message("应在7天内归还。", [self.citation()])])
        result = run_agent("设备借用期限？", model=model, toolbox=self.toolbox, max_tool_calls=2)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["tool_calls"], 2)
        self.assertEqual(result["model_turns"], 3)
        self.assertEqual(result["citations"], [self.citation()])

    def test_history_is_forwarded_but_does_not_authorize_unread_citation(self):
        history = [{"role": "user", "content": "先前在咨询公司设备借用。"}]
        original = copy.deepcopy(history)
        model = ScriptedModel([final_message("7天。", [self.citation()])])
        result = run_agent("那多久归还？", model=model, toolbox=self.toolbox, history=history)
        self.assertIn(history[0], model.calls[0])
        self.assertEqual(history, original)
        self.assertNotEqual(result["status"], "completed")
        self.assertEqual(result["citations"], [])

    def test_modified_source_changes_observed_evidence_and_answer(self):
        # This scripted model copies its read observation; it proves plumbing
        # follows current source data, not that a real LLM can reason correctly.
        def from_read_observation(messages, tools):
            observations = [json.loads(message["content"]) for message in messages if message.get("role") == "tool"]
            observation = next(item for item in reversed(observations) if "passages" in item)
            passage = observation["passages"][0]
            return final_message(passage["text"], [{"doc_id": "D001", "passage_id": passage["passage_id"],
                                                   "quote": passage["text"]}])

        before_model = ScriptedModel(self.search_and_read() + [from_read_observation])
        before = run_agent("设备借用期限？", model=before_model, toolbox=self.toolbox)
        changed = copy.deepcopy(DOCUMENTS)
        changed[0]["content"] = changed[0]["content"].replace("7天", "10天")
        self.write_documents(changed)
        after_model = ScriptedModel(self.search_and_read() + [from_read_observation])
        after = run_agent("设备借用期限？", model=after_model, toolbox=Toolbox(KnowledgeStore(self.path)))
        self.assertEqual(before["status"], "completed")
        self.assertEqual(after["status"], "completed")
        self.assertIn("7天", before["answer"])
        self.assertIn("10天", after["answer"])
        self.assertNotIn("7天", after["answer"])
        self.assertNotEqual(before["citations"], after["citations"])


if __name__ == "__main__":
    unittest.main()
