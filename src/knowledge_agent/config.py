"""只加载本项目配置，不输出凭证；不依赖第三方 dotenv。"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from urllib.parse import urlparse


class ConfigurationError(ValueError):
    pass


def read_env_file(path: Path) -> dict[str, str]:
    """支持 KEY=VALUE、整行注释及成对引号；不执行变量展开或代码。"""
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for number, original in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = original.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            raise ConfigurationError(f".env 第 {number} 行应使用 KEY=VALUE 格式。")
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            values[key] = value
    return values


@dataclass(frozen=True)
class Settings:
    api_key: str = field(repr=False)
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-flash"
    timeout: float = 60.0

    @classmethod
    def load(cls, root: Path) -> "Settings":
        local = read_env_file(Path(root) / ".env")

        def get(name: str, default: str = "") -> str:
            return os.environ.get(name, local.get(name, default)).strip()

        key = get("LLM_API_KEY")
        if not key:
            raise ConfigurationError("请在本机 .env 中填写 LLM_API_KEY，或设置同名进程环境变量。")
        base_url = get("LLM_BASE_URL", "https://api.deepseek.com").rstrip("/")
        parsed = urlparse(base_url)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ConfigurationError("LLM_BASE_URL 应为不含凭证、查询参数的 API 地址。")
        if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ConfigurationError("非本地 API 必须使用 HTTPS。")
        model = get("LLM_MODEL", "deepseek-flash")
        if not model:
            raise ConfigurationError("LLM_MODEL 不能为空。")
        try:
            timeout = float(get("LLM_TIMEOUT", "60"))
        except ValueError as exc:
            raise ConfigurationError("LLM_TIMEOUT 应为秒数。") from exc
        if not 1 <= timeout <= 180:
            raise ConfigurationError("LLM_TIMEOUT 应在 1 到 180 秒之间。")
        return cls(api_key=key, base_url=base_url, model=model, timeout=timeout)
