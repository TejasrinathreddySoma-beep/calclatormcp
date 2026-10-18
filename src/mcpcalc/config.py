"""Configuration: defaults + optional config.yaml (path from --config or $MCPCALC_CONFIG)."""
from __future__ import annotations

import copy
import os
from pathlib import Path

DEFAULTS: dict = {
    "llm": {"provider": "ollama", "model": "qwen2.5:7b", "host": "http://localhost:11434", "temperature": 0},
    "translator": {"strategy": "full", "max_retries": 2},
    "backend": "python",
    "angle_mode": "deg",
    "server": {"transport": "stdio", "host": "127.0.0.1", "port": 8765, "workers": 4,
               "queue_size": 100, "timeout_s": 30},
    "safety": {"dry_run": False, "max_expression_length": 200, "max_nodes": 120, "allowed_functions": "all"},
    "database": {"path": "data/mcpcalc.db"},
}


def _merge(base: dict, override: dict) -> dict:
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
    return base


def load_config(path: str | os.PathLike | None = None) -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    candidate = Path(path or os.environ.get("MCPCALC_CONFIG", "config.yaml"))
    if candidate.exists():
        import yaml

        _merge(cfg, yaml.safe_load(candidate.read_text(encoding="utf-8")) or {})
    return cfg
