"""真实 API 工具协议检查，不替代正式知识问答验收；仅依赖标准库。"""

from __future__ import annotations

import json
from pathlib import Path
import secrets
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from knowledge_agent.config import ConfigurationError, Settings
from knowledge_agent.model import LiveModel, ModelError


def main() -> int:
    try:
        model = LiveModel(Settings.load(ROOT))
        marker = secrets.token_hex(6)
        tools = [{
            "type": "function",
            "function": {
                "name": "read_probe_document",
                "description": "读取临时合成文档，并取得尚未告知用户的随机校验码。",
                "parameters": {
                    "type": "object",
                    "properties": {"doc_id": {"type": "string"}},
                    "required": ["doc_id"],
                    "additionalProperties": False,
                },
            },
        }]
        messages = [{"role": "user", "content": (
            "先调用 read_probe_document 读取 PROBE-001，再准确复述工具返回的校验码。"
            "不要猜测，读取一次后直接回答。"
        )}]
        first = model.complete(messages, tools)
        calls = first.get("tool_calls", [])
        if len(calls) != 1:
            print("检查未通过：模型没有按指令返回一次工具调用。")
            return 1
        call = calls[0]
        arguments = json.loads(call["function"]["arguments"])
        if call["function"]["name"] != "read_probe_document" or arguments != {"doc_id": "PROBE-001"}:
            print("检查未通过：模型给出的工具名称或参数不符合检查要求。")
            return 1
        observation = {"doc_id": "PROBE-001", "content": f"本合成文档的校验码是 {marker}。"}
        messages.extend([first, {
            "role": "tool", "tool_call_id": call["id"],
            "content": json.dumps(observation, ensure_ascii=False),
        }])
        final = model.complete(messages, tools)
        if final.get("tool_calls") or marker not in (final.get("content") or ""):
            print("检查未通过：模型没有结束，或未在回答中使用工具返回的校验码。")
            return 1
        print(json.dumps({
            "status": "passed", "mode": "live", "configured_model": model.name,
            "reported_model": model.resolved_model, "tool": call["function"]["name"],
            "arguments": arguments, "observation": observation, "answer": final["content"],
            "boundary": "只验证真实 API 与工具协议，不替代正式业务验收。",
        }, ensure_ascii=False, indent=2))
        return 0
    except (ConfigurationError, ModelError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc),
                          "kind": getattr(exc, "kind", "configuration_error"),
                          "http_status": getattr(exc, "status_code", None)}, ensure_ascii=False))
        return 2
    except (KeyError, TypeError, ValueError):
        print("检查未通过：模型工具动作格式无效。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
