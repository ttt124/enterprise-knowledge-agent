"""明确标注的离线工具流程模拟器；没有模型推理能力，不作为真实效果证据。"""

from __future__ import annotations

import json


class OfflineModel:
    mode = "mock"
    name = "offline-flow-simulator"

    def complete(self, messages: list[dict], tools: list[dict]) -> dict:
        observations = [json.loads(item["content"]) for item in messages if item.get("role") == "tool"]
        if not observations:
            # 固定模拟路径只展示一次检索及按候选读取，不宣称满足真实决策要求。
            question = next(item["content"] for item in reversed(messages) if item.get("role") == "user")
            return self._call("search_documents", {"query": question, "reason": "离线模拟：展示检索工具流程"}, 1)
        search = next((item for item in observations if "matches" in item), None)
        read_ids = {item.get("doc_id") for item in observations if "passages" in item}
        if observations[-1].get("ok") is not False and search:
            for candidate in search.get("matches", []):
                if candidate["doc_id"] not in read_ids:
                    return self._call("read_document", {"doc_id": candidate["doc_id"],
                                      "reason": "离线模拟：读取候选原文"}, len(observations) + 1)
        return {"role": "assistant", "content": json.dumps({
            "answer": "离线Mock流程已结束；它未调用真实模型，不能提供经过模型判断的业务结论。",
            "citations": [], "gaps": ["需要使用 live 模式验证模型决策及业务答案"],
            "status": "incomplete", "reason": "offline_mock_boundary",
        }, ensure_ascii=False)}

    @staticmethod
    def _call(name: str, arguments: dict, index: int) -> dict:
        return {"role": "assistant", "content": None, "tool_calls": [{
            "id": f"mock-{index}", "type": "function", "function": {
                "name": name, "arguments": json.dumps(arguments, ensure_ascii=False),
            },
        }]}
