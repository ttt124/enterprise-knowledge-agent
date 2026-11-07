"""Tool regressions using isolated data; no network, settings, or API keys."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from knowledge_agent.tools import KnowledgeStore, Toolbox


DOCUMENTS = [
    {"doc_id": "D001", "title": "设备借用制度", "version_date": "2026-01-01",
     "topic": "设备借用", "keywords": ["设备", "借用", "归还"],
     "content": "员工借用公司设备后，应在7天内归还。\n\n归还时应由管理员登记。"},
    {"doc_id": "D002", "title": "差旅报销规定", "version_date": "2026-01-01",
     "topic": "差旅报销", "keywords": ["差旅", "报销", "期限"],
     "content": "员工应在差旅结束后30天内提交报销申请。"},
    {"doc_id": "D003", "title": "差旅报销说明", "version_date": "2026-02-01",
     "topic": "差旅报销", "keywords": ["差旅", "报销", "期限"],
     "content": "员工应在差旅结束后15天内提交报销申请。"},
]


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="knowledge-test-")
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "documents.json"
        self.write_documents(DOCUMENTS)
        self.toolbox = Toolbox(KnowledgeStore(self.path))

    def write_documents(self, documents):
        self.path.write_text(json.dumps(documents, ensure_ascii=False), encoding="utf-8")

    def search(self, query, toolbox=None):
        return (toolbox or self.toolbox).execute("search_documents", {"query": query, "reason": "测试召回"})

    def test_colloquial_synonyms_recall_device_policy(self):
        result = self.search("展示机拿一周再还")
        self.assertIs(result["ok"], True)
        self.assertIn("D001", {item["doc_id"] for item in result["matches"]})

    def test_conflicting_policies_are_both_recalled(self):
        result = self.search("差旅报销期限")
        self.assertTrue({"D002", "D003"}.issubset({item["doc_id"] for item in result["matches"]}))

    def test_new_conflicting_device_document_is_recalled(self):
        documents = copy.deepcopy(DOCUMENTS)
        documents.append({"doc_id": "D009", "title": "设备借用补充规定", "version_date": "2026-03-01",
                          "topic": "设备借用", "keywords": ["设备", "借用", "归还"],
                          "content": "员工借用公司设备后，应在3天内归还。"})
        self.write_documents(documents)
        result = self.search("借用设备多久归还", Toolbox(KnowledgeStore(self.path)))
        self.assertTrue({"D001", "D009"}.issubset({item["doc_id"] for item in result["matches"]}))

    def test_empty_search_is_success_not_tool_failure(self):
        empty = self.search("购房补贴金额")
        self.assertIs(empty["ok"], True)
        self.assertEqual(empty["matches"], [])
        failing = Toolbox(KnowledgeStore(self.path), failures={"search_documents": -1})
        failure = self.search("设备借用", failing)
        self.assertIs(failure["ok"], False)
        self.assertTrue(failure.get("error"))

    def test_unknown_tool_invalid_arguments_and_missing_doc_are_explicit_errors(self):
        for name, arguments in [
            ("delete_document", {"doc_id": "D001", "reason": "测试错误"}),
            ("search_documents", {"reason": "缺少query"}),
            ("search_documents", {"query": "设备", "reason": "", "unexpected": True}),
            ("read_document", {"doc_id": "missing", "reason": "测试不存在文档"}),
        ]:
            with self.subTest(name=name, arguments=arguments):
                result = self.toolbox.execute(name, arguments)
                self.assertIs(result["ok"], False)
                self.assertTrue(result.get("error"))

    def test_read_returns_stable_ids_and_exact_original_paragraphs(self):
        result = self.toolbox.execute("read_document", {"doc_id": "D001", "reason": "核对原文"})
        self.assertIs(result["ok"], True)
        self.assertEqual(result["passages"], [
            {"passage_id": "D001#p1", "text": "员工借用公司设备后，应在7天内归还。"},
            {"passage_id": "D001#p2", "text": "归还时应由管理员登记。"},
        ])

    def test_transient_failure_recovers_and_persistent_failure_does_not(self):
        arguments = {"doc_id": "D001", "reason": "读取原文"}
        transient = Toolbox(KnowledgeStore(self.path), failures={"read_document": 1})
        self.assertIs(transient.execute("read_document", arguments)["ok"], False)
        self.assertIs(transient.execute("read_document", arguments)["ok"], True)
        persistent = Toolbox(KnowledgeStore(self.path), failures={"read_document": -1})
        self.assertIs(persistent.execute("read_document", arguments)["ok"], False)
        self.assertIs(persistent.execute("read_document", arguments)["ok"], False)

    def test_source_edit_changes_search_observation(self):
        before = self.search("设备借用")
        changed = copy.deepcopy(DOCUMENTS)
        changed[0]["content"] = changed[0]["content"].replace("7天", "10天")
        self.write_documents(changed)
        after = self.search("设备借用", Toolbox(KnowledgeStore(self.path)))
        self.assertNotEqual(before, after)
        self.assertIn("10天", json.dumps(after, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
