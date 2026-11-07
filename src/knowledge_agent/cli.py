"""可复制的 CLI 入口；默认离线模式不加载任何 API 凭证。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .agent import run_agent
from .config import ConfigurationError, Settings
from .mock import OfflineModel
from .model import LiveModel
from .tools import KnowledgeStore, Toolbox


ROOT = Path(__file__).resolve().parents[2]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="带原文引用和执行Trace的小型企业知识问答Agent")
    parser.add_argument("--question", required=True, help="本次问题")
    parser.add_argument("--mode", choices=("live", "mock"), default="mock")
    parser.add_argument("--data", type=Path, default=ROOT / "data" / "documents.json")
    parser.add_argument("--history", type=Path, help="可选user/assistant历史JSON数组")
    parser.add_argument("--max-tool-calls", type=int, default=8)
    parser.add_argument("--max-model-turns", type=int, default=12)
    parser.add_argument("--fail-tool", choices=("search_documents", "read_document"))
    parser.add_argument("--fail-times", type=int, default=1, help="失败次数，-1为持续失败")
    parser.add_argument("--output", type=Path, help="将实际结果（含Trace）保存为JSON")
    args = parser.parse_args(argv)
    if args.max_tool_calls < 0 or args.max_model_turns < 1 or args.fail_times < -1:
        parser.error("调用预算不能为负，模型轮数至少1，故障次数至少-1。")
    try:
        history = json.loads(args.history.read_text(encoding="utf-8-sig")) if args.history else []
        model = LiveModel(Settings.load(ROOT)) if args.mode == "live" else OfflineModel()
        failures = {args.fail_tool: args.fail_times} if args.fail_tool else None
        result = run_agent(args.question, model=model, toolbox=Toolbox(KnowledgeStore(args.data), failures),
                           history=history, max_tool_calls=args.max_tool_calls,
                           max_model_turns=args.max_model_turns)
        rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        print(rendered, end="")
        # 非成功状态可供脚本识别；冲突/资料不足是业务预期结果，不等于程序崩溃。
        return 0 if result["status"] == "completed" else 2
    except (ConfigurationError, OSError, ValueError) as exc:
        print(json.dumps({"status": "incomplete", "error": str(exc)}, ensure_ascii=False))
        return 1
