"""可审计的本地资料检索工具；仅使用标准库，不执行模型生成的代码。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


MAX_QUERY_LENGTH = 1000
MAX_REASON_LENGTH = 500
MAX_DOC_ID_LENGTH = 64

# 同义词只统一检索表达，不携带制度结论，也不推断文档之间的优先级。
_SYNONYM_GROUPS = (
    ("演示设备", "展示机", "样机", "演示机"),
    ("差旅", "出差"),
    ("归还", "还设备", "还回去", "还给谁"),
)
_GENERIC_BIGRAMS = {"流程", "申请", "提交", "办理", "时间", "规定", "要求", "员工", "完成", "管理", "使用", "材料", "审批"}


def _error(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "error": {"code": code, "message": message}}


def _normalize(text: str) -> str:
    value = text.lower()
    for group in _SYNONYM_GROUPS:
        for synonym in group[1:]:
            value = value.replace(synonym, group[0])
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", value)


def _bigrams(text: str) -> set[str]:
    # 仅取相邻汉字；避免问号、英文缩写或通用流程词制造大批弱相关命中。
    return {
        text[i : i + 2]
        for i in range(len(text) - 1)
        if all("\u4e00" <= char <= "\u9fff" for char in text[i : i + 2])
        and text[i : i + 2] not in _GENERIC_BIGRAMS
    }


def _validate_text(value: Any, name: str, maximum: int, *, allow_blank: bool = False) -> dict[str, Any] | None:
    if not isinstance(value, str):
        return _error("invalid_arguments", f"{name} 必须是字符串。")
    if len(value) > maximum:
        return _error("invalid_arguments", f"{name} 长度不能超过 {maximum} 个字符。")
    if not allow_blank and not value.strip():
        return _error("invalid_arguments", f"{name} 不能为空。")
    return None


class KnowledgeStore:
    """读取 JSON 数组；documents 保留每份原始文档及原文。"""

    def __init__(self, path: Path):
        self.documents: dict[str, dict[str, Any]] = {}
        self._load_error: dict[str, Any] | None = None
        if not isinstance(path, Path):
            self._load_error = _error("invalid_arguments", "资料路径必须是 pathlib.Path。")
            return
        try:
            source = path / "documents.json" if path.is_dir() else path
            raw = json.loads(source.read_text(encoding="utf-8-sig"))
            if not isinstance(raw, list) or not raw:
                raise ValueError("资料文件必须包含非空 JSON 数组")
            documents: dict[str, dict[str, Any]] = {}
            for document in raw:
                if not isinstance(document, dict):
                    raise ValueError("每份资料必须是对象")
                for field in ("doc_id", "title", "version_date", "topic", "content"):
                    if not isinstance(document.get(field), str) or not document[field].strip():
                        raise ValueError(f"资料字段 {field} 必须是非空字符串")
                if len(document["doc_id"]) > MAX_DOC_ID_LENGTH or document["doc_id"] in documents:
                    raise ValueError("资料编号重复或过长")
                keywords = document.get("keywords")
                if not isinstance(keywords, list) or any(not isinstance(word, str) or not word.strip() for word in keywords):
                    raise ValueError("keywords 必须是非空字符串组成的列表")
                documents[document["doc_id"]] = document
            self.documents = documents
        except (OSError, UnicodeError, ValueError, TypeError):
            # 配置错误保持为显式失败，不能被上层误解为“知识库无相关内容”。
            self._load_error = _error("tool_error", "知识库加载失败，请检查资料路径及 JSON 文档格式。")

    def search(self, query: str) -> dict[str, Any]:
        invalid = _validate_text(query, "query", MAX_QUERY_LENGTH, allow_blank=True)
        if invalid:
            return invalid
        if self._load_error:
            return self._load_error
        result: dict[str, Any] = {"ok": True, "query": query, "matches": [], "total": 0, "truncated": False}
        normalized = _normalize(query)
        if not normalized:
            return result
        query_bigrams = _bigrams(normalized)
        topic_scores: dict[str, float] = {}
        for document in self.documents.values():
            topic = document["topic"]
            terms = {_normalize(term) for term in [topic, *document["keywords"]]}
            direct = sum(1 + min(len(term), 8) / 8 for term in terms if term and term in normalized)
            metadata_bigrams = _bigrams(_normalize(" ".join([document["title"], topic, *document["keywords"]])))
            overlap = len(query_bigrams & metadata_bigrams)
            # bigram 仅补充近似表达，至少两处匹配才建立主题，单个泛词不扩散召回。
            score = direct * 10 + (min(overlap, 6) if overlap >= 2 else 0)
            if score > 0:
                topic_scores[topic] = max(score, topic_scores.get(topic, 0))
        ranked = [doc for doc in self.documents.values() if doc["topic"] in topic_scores]
        ranked.sort(key=lambda doc: (-topic_scores[doc["topic"]], doc["doc_id"]))
        # 同一主题全部返回，不按新旧日期过滤：冲突资料必须保留给后续逐篇读取。
        for document in ranked:
            paragraphs = self._passages(document)
            best = max(paragraphs, key=lambda item: len(query_bigrams & _bigrams(_normalize(item["text"])) ))
            result["matches"].append({
                "doc_id": document["doc_id"],
                "title": document["title"],
                "version_date": document["version_date"],
                "topic": document["topic"],
                "snippet": best["text"][:240],
            })
        result["total"] = len(result["matches"])
        return result

    @staticmethod
    def _passages(document: dict[str, Any]) -> list[dict[str, str]]:
        # 按空行定位段落；不改写句子或剔除原文中的字符。
        pieces = re.split(r"\r?\n[ \t]*\r?\n", document["content"])
        return [
            {"passage_id": f"{document['doc_id']}#p{index}", "text": piece}
            for index, piece in enumerate(pieces, 1)
            if piece.strip()
        ]

    def read(self, doc_id: str) -> dict[str, Any]:
        invalid = _validate_text(doc_id, "doc_id", MAX_DOC_ID_LENGTH)
        if invalid:
            return invalid
        if self._load_error:
            return self._load_error
        document = self.documents.get(doc_id)
        if document is None:
            return _error("not_found", f"未找到文档 {doc_id}。")
        return {
            "ok": True,
            "doc_id": document["doc_id"],
            "title": document["title"],
            "version_date": document["version_date"],
            "topic": document["topic"],
            "passages": self._passages(document),
        }


class Toolbox:
    """受限的工具分发入口，支持按工具名注入可恢复或持续故障。"""

    def __init__(self, store: KnowledgeStore, failures: dict[str, int] | None = None):
        self.store = store
        self.failures = dict(failures) if isinstance(failures, dict) else {}
        self._configuration_error = failures is not None and (
            not isinstance(failures, dict)
            or any(name not in {"search_documents", "read_document"} or type(count) is not int or count < -1 for name, count in self.failures.items())
        )

    def execute(self, name: str, arguments: dict) -> dict[str, Any]:
        invalid = _validate_text(name, "工具名", 80)
        if invalid:
            return invalid
        if name not in {"search_documents", "read_document"}:
            return _error("unknown_tool", f"不支持的工具：{name}。")
        if not isinstance(arguments, dict):
            return _error("invalid_arguments", "工具参数必须是对象。")
        primary = "query" if name == "search_documents" else "doc_id"
        if set(arguments) != {primary, "reason"}:
            return _error("invalid_arguments", f"参数必须且只能包含 {primary} 和 reason。")
        for field, limit in ((primary, MAX_QUERY_LENGTH if primary == "query" else MAX_DOC_ID_LENGTH), ("reason", MAX_REASON_LENGTH)):
            invalid = _validate_text(arguments[field], field, limit)
            if invalid:
                return invalid
        if self._configuration_error:
            return _error("tool_error", "工具故障注入配置无效。")
        remaining = self.failures.get(name, 0)
        if remaining == -1 or remaining > 0:
            if remaining > 0:
                self.failures[name] = remaining - 1
            return _error("tool_error", f"{name} 暂时不可用（模拟工具故障）。")
        try:
            # reason 仅用于透明展示动作依据，不参与检索、读取或业务规则判断。
            if name == "search_documents":
                return self.store.search(arguments["query"])
            return self.store.read(arguments["doc_id"])
        except Exception:
            return _error("tool_error", f"{name} 执行失败，请稍后重试。")
