"""Run reproducible knowledge-agent cases; mock mode never loads API settings.

This is a small assertion-based regression suite, not an independent judge of
answer correctness. Live and mock results are kept in separate, dated runs.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import sys
import tempfile
import time
import traceback

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledge_agent.agent import run_agent
from knowledge_agent.tools import KnowledgeStore, Toolbox


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def prepare_documents(documents: list[dict], case: dict) -> list[dict]:
    """Mutate a private copy; the project's source data is never changed."""
    snapshot = copy.deepcopy(documents)
    mutation = case.get("mutation", {})
    if mutation.get("type") == "replace":
        document = next(doc for doc in snapshot if doc["doc_id"] == mutation["doc_id"])
        old = mutation["old"]
        if old not in document["content"]:
            raise ValueError(f"Mutation source text {old!r} absent in {mutation['doc_id']}")
        document["content"] = document["content"].replace(old, mutation["new"])
    elif mutation.get("type") == "append_conflict":
        snapshot.append({
            "doc_id": mutation["doc_id"],
            "title": "设备借用补充规定（待确认）",
            "version_date": "2026-11-07",
            "topic": "设备借用",
            "keywords": ["设备", "借用", "归还", "展示机", "3天"],
            "content": "员工借用公司设备后，应在3天内归还。\n\n本规定未说明与其他设备借用文件的优先关系。",
        })
    elif mutation:
        raise ValueError(f"Unsupported mutation: {mutation.get('type')}")
    return snapshot


def check_output(result: dict, case: dict, documents: list[dict]) -> list[dict]:
    """Check actual outputs and source quotes, without manufacturing answers."""
    expected = case["expected"]
    checks = []

    def check(name, passed, detail=""):
        checks.append({"check": name, "passed": bool(passed), "detail": detail})

    check("status", result.get("status") in expected["status"],
          f"actual={result.get('status')!r}; allowed={expected['status']!r}")
    answer = result.get("answer", "")
    check("answer_is_text", isinstance(answer, str))
    if not isinstance(answer, str):
        answer = ""
    if "answer_regex" in expected:
        check("answer_contains_expected_fact", re.search(expected["answer_regex"], answer) is not None)
    if "forbidden_answer_regex" in expected:
        check("answer_omits_forbidden_claim", re.search(expected["forbidden_answer_regex"], answer) is None)

    citations = result.get("citations", [])
    check("citations_are_list", isinstance(citations, list))
    if not isinstance(citations, list):
        citations = []
    cited_ids = {c.get("doc_id") for c in citations if isinstance(c, dict)}
    for doc_id in expected.get("citation_doc_ids", []):
        check(f"cites_{doc_id}", doc_id in cited_ids)
    if expected.get("no_citations"):
        check("no_unsupported_citations", not citations)

    trace = result.get("trace", [])
    check("trace_is_list", isinstance(trace, list))
    if not isinstance(trace, list):
        trace = []
    successfully_read = set()
    had_failure = False
    for event in trace:
        if not isinstance(event, dict):
            continue
        observation = event.get("observation", {})
        if not isinstance(observation, dict):
            continue
        had_failure = had_failure or observation.get("ok") is False
        if event.get("tool") == "read_document" and observation.get("ok") is True:
            doc_id = observation.get("doc_id") or event.get("arguments", {}).get("doc_id")
            for passage in observation.get("passages", []):
                successfully_read.add((doc_id, passage.get("passage_id"), passage.get("text")))

    # Independently reconstruct source passages and ensure the agent actually read
    # the quoted passage during this run; search snippets do not count as reading.
    source_passages = {}
    for doc in documents:
        for number, paragraph in enumerate(re.split(r"\r?\n[ \t]*\r?\n", doc["content"]), 1):
            if paragraph.strip():
                source_passages[(doc["doc_id"], f"{doc['doc_id']}#p{number}")] = paragraph
    for index, citation in enumerate(citations, 1):
        valid_shape = isinstance(citation, dict)
        check(f"citation_{index}_shape", valid_shape)
        if not valid_shape:
            continue
        key = (citation.get("doc_id"), citation.get("passage_id"))
        quote = citation.get("quote")
        source = source_passages.get(key, "")
        verbatim = isinstance(quote, str) and bool(quote.strip()) and quote in source
        check(f"citation_{index}_verbatim", verbatim)
        was_read = any(d == key[0] and p == key[1] and isinstance(t, str)
                       and isinstance(quote, str) and quote in t
                       for d, p, t in successfully_read)
        check(f"citation_{index}_was_read", was_read)
    if expected.get("tool_failure_observed"):
        check("tool_failure_observed", had_failure)

    tool_calls = result.get("tool_calls")
    check("tool_calls_is_integer", isinstance(tool_calls, int) and not isinstance(tool_calls, bool))
    budget = case.get("max_tool_calls", case.get("effective_max_tool_calls", 8))
    check("tool_budget_respected", isinstance(tool_calls, int) and 0 <= tool_calls <= budget)
    if "max_tool_calls" in expected:
        check("requested_budget_is_binding", isinstance(tool_calls, int) and tool_calls <= expected["max_tool_calls"])
    return checks


def check_mock_output(result: dict, case: dict, documents: list[dict]) -> list[dict]:
    """OfflineModel demonstrates tools only; business expectations stay ungraded."""
    flow_case = copy.deepcopy(case)
    flow_case["expected"] = {"status": ["incomplete"], "no_citations": True}
    if case["expected"].get("tool_failure_observed"):
        flow_case["expected"]["tool_failure_observed"] = True
    checks = check_output(result, flow_case, documents)
    trace = result.get("trace", [])
    if not isinstance(trace, list):
        trace = []
    calls = [event for event in trace if isinstance(event, dict) and event.get("event") == "tool_call"]
    checks.append({"check": "tool_count_matches_trace", "passed": result.get("tool_calls") == len(calls), "detail": ""})
    budget = case.get("max_tool_calls", case.get("effective_max_tool_calls", 8))
    checks.append({"check": "actual_tools_exercised", "passed": bool(calls) or budget == 0, "detail": ""})
    checks.append({"check": "terminal_event_present", "passed": any(
        isinstance(event, dict) and event.get("event") == "final" for event in trace), "detail": ""})
    return checks


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("mock", "live"), default="mock")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--case", action="append", default=[], help="Case ID, repeatable")
    parser.add_argument("--max-tool-calls", type=int, default=8)
    parser.add_argument("--delay", type=float, default=0, help="Seconds between cases (default: 0)")
    args = parser.parse_args(argv)
    if args.max_tool_calls < 0:
        parser.error("--max-tool-calls must be nonnegative")
    if not math.isfinite(args.delay) or args.delay < 0:
        parser.error("--delay must be finite and nonnegative")
    cases = json.loads((PROJECT_ROOT / "data" / "evaluation_cases.json").read_text(encoding="utf-8"))
    known_ids = {case["id"] for case in cases}
    if set(args.case) - known_ids:
        parser.error(f"Unknown case IDs: {sorted(set(args.case) - known_ids)}")
    cases = [case for case in cases if not args.case or case["id"] in args.case]
    source_documents = json.loads((PROJECT_ROOT / "data" / "documents.json").read_text(encoding="utf-8"))
    if args.mode == "live":
        from knowledge_agent.config import Settings
        from knowledge_agent.model import LiveModel
        model = LiveModel(Settings.load(PROJECT_ROOT))
    else:
        from knowledge_agent.mock import OfflineModel
        model = OfflineModel()

    base_dir = args.output_dir or PROJECT_ROOT / "examples" / args.mode
    if not base_dir.is_absolute():
        base_dir = PROJECT_ROOT / base_dir
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_dir = base_dir / f"run-{timestamp}"
    run_dir.mkdir(parents=True, exist_ok=False)
    records = []
    for case_index, original_case in enumerate(cases):
        if case_index and args.delay:
            time.sleep(args.delay)
        case = copy.deepcopy(original_case)
        case["effective_max_tool_calls"] = case.get("max_tool_calls", args.max_tool_calls)
        case_dir = run_dir / case["id"]
        case_dir.mkdir()
        write_json(case_dir / "input.json", {
            "question": case["question"], "history": case.get("history", []),
            "mode": args.mode, "model": model.name,
            "max_tool_calls": case["effective_max_tool_calls"],
            "failures": case.get("failures", {}), "mutation": case.get("mutation"),
            "expected": case["expected"],
            "validation_scope": "offline_flow" if args.mode == "mock" else "business_and_evidence",
            "business_expectations_evaluated": args.mode == "live",
        })
        started = time.monotonic()
        try:
            documents = prepare_documents(source_documents, case)
            write_json(case_dir / "documents.json", documents)
            # Even non-mutated cases run from a private snapshot. No case can
            # accidentally modify data used by a later case or the default app.
            with tempfile.TemporaryDirectory(prefix="knowledge-eval-") as temporary:
                temporary_path = Path(temporary) / "documents.json"
                write_json(temporary_path, documents)
                toolbox = Toolbox(KnowledgeStore(temporary_path), failures=case.get("failures", {}))
                result = run_agent(case["question"], model=model, toolbox=toolbox,
                                   history=case.get("history", []),
                                   max_tool_calls=case["effective_max_tool_calls"])
            write_json(case_dir / "output.json", result)
            write_json(case_dir / "trace.json", result.get("trace", []))
            checks = (check_mock_output(result, case, documents) if args.mode == "mock"
                      else check_output(result, case, documents))
            record = {"id": case["id"], "name": case["name"],
                      "passed": all(check["passed"] for check in checks),
                      "status": result.get("status"), "checks": checks}
        except Exception as exc:
            error = {"error": type(exc).__name__, "message": str(exc),
                     "traceback": traceback.format_exc()}
            write_json(case_dir / "output.json", error)
            write_json(case_dir / "trace.json", [])
            record = {"id": case["id"], "name": case["name"], "passed": False,
                      "status": "evaluation_error", "checks": [], "error": error}
        record["elapsed_seconds"] = round(time.monotonic() - started, 3)
        record["business_expectations"] = {
            "status": "not_evaluated" if args.mode == "mock" else "evaluated",
            "expected": case["expected"],
            "reason": ("Offline simulator has no business reasoning ability; only flow assertions run."
                       if args.mode == "mock" else "Assertions applied to actual live output."),
        }
        records.append(record)
        print(f"{record['id']} {'PASS' if record['passed'] else 'FAIL'} {record['status']}")

    summary = {"mode": args.mode, "model": model.name, "run_directory": str(run_dir),
               "created_at_utc": timestamp, "total": len(records),
               "passed": sum(record["passed"] for record in records),
               "results": records,
               "scope": "offline_flow" if args.mode == "mock" else "business_and_evidence",
               "business_expectations_evaluated": args.mode == "live",
               "limitation": "Assertion-based checks, not an independent answer-quality judge. Offline flow results do not establish model or business quality."}
    write_json(run_dir / "summary.json", summary)
    report = [f"# Knowledge Agent 评估（{args.mode}）", "", f"模型：`{model.name}`", "",
              f"{'离线流程断言' if args.mode == 'mock' else '业务与证据断言'}通过 {summary['passed']}/{summary['total']}。", "",
              ("本报告检查离线结束状态、无伪造引用、实际工具调用与预算、终止事件和注入故障记录。"
               if args.mode == "mock" else "本报告检查状态、必需引用、逐字来源、已读证据与调用预算。"),
              ("本次为 offline_flow：业务期望全部标记 not_evaluated；模拟器应返回 incomplete 且不伪造引用。通过比例不代表模型效果。"
               if args.mode == "mock" else "本次对真实输出检查各用例业务期望与证据；仍需人工复核语义与适用范围。"),
              "每例保留 input.json、output.json、trace.json 和 documents.json；失败记录同样保留。", "",
              "| 用例 | 名称 | 结果 | 实际状态 |", "| --- | --- | --- | --- |"]
    for record in records:
        report.append(f"| {record['id']} | {record['name']} | {'通过' if record['passed'] else '失败'} | {record['status']} |")
    for record in records:
        failures = [check for check in record["checks"] if not check["passed"]]
        if failures or "error" in record:
            report.extend(["", f"## {record['id']} 失败明细", ""])
            report.extend(f"- {item['check']}: {item['detail']}" for item in failures)
            if "error" in record:
                report.append(f"- {record['error']['error']}: {record['error']['message']}")
    (run_dir / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"Saved {run_dir}")
    return 0 if summary["passed"] == summary["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
