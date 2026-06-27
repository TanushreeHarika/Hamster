from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    openrouter_api_key: str
    max_tokens: int
    max_failures: int
    model: str


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _read_int(values: dict[str, str], key: str, default: int) -> int:
    raw = values.get(key, str(default))
    try:
        parsed = int(raw)
    except ValueError as exc:
        raise ValueError(f"{key} must be an integer in .env, got {raw!r}") from exc
    if parsed <= 0:
        raise ValueError(f"{key} must be greater than zero in .env")
    return parsed


def load_config(project_root: Path) -> Config:
    values = load_env_file(project_root / ".env")
    return Config(
        openrouter_api_key=values.get("OPENROUTER_API_KEY", ""),
        max_tokens=_read_int(values, "MAX_TOKENS", 4096),
        max_failures=_read_int(values, "MAX_FAILURES", 3),
        model=values.get("OPENROUTER_MODEL", "anthropic/claude-3.5-sonnet"),
    )
