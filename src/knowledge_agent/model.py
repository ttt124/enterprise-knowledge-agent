"""用标准库调用兼容 Chat Completions 的真实模型，不自动重试业务动作。"""

from __future__ import annotations

import json
import socket
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .config import Settings


class ModelError(RuntimeError):
    """只包含可公开的错误类型，避免将服务端原文或请求头写入日志。"""

    def __init__(self, kind: str, message: str, status_code: int | None = None):
        super().__init__(message)
        self.kind = kind
        self.status_code = status_code


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # API 不需要跳转；拒绝重定向，避免 Authorization 被带往其他地址。
        return None


class LiveModel:
    mode = "live"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.name = settings.model
        self.resolved_model: str | None = None
        self.last_usage: dict = {}

    def complete(self, messages: list[dict], tools: list[dict]) -> dict:
        payload = {
            "model": self.name,
            "messages": messages,
            "temperature": 0,
            "stream": False,
            "max_tokens": 2400,
        }
        if tools:
            payload.update({"tools": tools, "tool_choice": "auto"})
        if urlparse(self.settings.base_url).hostname == "api.deepseek.com":
            payload["thinking"] = {"type": "disabled"}
        request = Request(
            self.settings.base_url + "/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": "Bearer " + self.settings.api_key,
                "Content-Type": "application/json",
                "User-Agent": "enterprise-knowledge-agent/0.1.0",
            },
            method="POST",
        )
        self.last_usage = {}
        try:
            with build_opener(_NoRedirect()).open(request, timeout=self.settings.timeout) as response:
                raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ModelError("invalid_response", "模型响应超过大小限制。")
            result = json.loads(raw.decode("utf-8"))
            choice = result["choices"][0]
            if choice.get("finish_reason") == "length":
                raise ModelError("truncated_response", "模型输出达到长度限制，本轮未取得完整动作。")
            message = choice["message"]
            if not isinstance(message, dict) or message.get("role") != "assistant":
                raise ModelError("invalid_response", "模型未返回有效 assistant 消息。")
            self.last_usage = {
                name: value for name, value in result.get("usage", {}).items()
                if name in {"prompt_tokens", "completion_tokens", "total_tokens"}
                and isinstance(value, int)
            }
            self.resolved_model = result.get("model")
            # 非思考模式下只保留协议需要的字段；不记录内部推理字段。
            clean = {"role": "assistant", "content": message.get("content")}
            if message.get("tool_calls"):
                clean["tool_calls"] = message["tool_calls"]
            return clean
        except HTTPError as exc:
            status = exc.code
            exc.close()
            category, hint = {
                301: ("redirect_rejected", "API 返回重定向，已停止。请核对最终 API 地址。"),
                302: ("redirect_rejected", "API 返回重定向，已停止。请核对最终 API 地址。"),
                303: ("redirect_rejected", "API 返回重定向，已停止。请核对最终 API 地址。"),
                307: ("redirect_rejected", "API 返回重定向，已停止。请核对最终 API 地址。"),
                308: ("redirect_rejected", "API 返回重定向，已停止。请核对最终 API 地址。"),
                400: ("bad_request", "模型 API 拒绝了请求，请核对模型名及工具调用协议。"),
                401: ("unauthorized", "API 鉴权失败，请在本机检查密钥。"),
                402: ("insufficient_balance", "API 余额或额度不足，请在服务商控制台处理。"),
                403: ("forbidden", "API 权限不足，请检查账户或模型访问权限。"),
                404: ("not_found", "API 地址或模型不存在，请核对配置。"),
                429: ("rate_limited", "API 请求达到限流或额度限制，请稍后重试并检查控制台。"),
            }.get(status, ("http_error", "模型 API 服务异常，本次未取得结果。"))
            raise ModelError(category, hint, status) from None
        except (TimeoutError, socket.timeout):
            raise ModelError("timeout", "模型 API 调用超时，本次任务未完成。") from None
        except URLError:
            raise ModelError("connection_error", "无法连接模型 API，请检查本机网络与代理。") from None
        except (ValueError, KeyError, IndexError, TypeError, UnicodeError):
            raise ModelError("invalid_response", "模型返回格式无效，本次未取得可执行动作。") from None
