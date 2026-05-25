from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import yaml

_HOME = Path.home()

# Default data paths per tool — overridable via config/tools.yaml
DEFAULT_TOOL_PATHS: Dict[str, Path] = {
    "antigravity": _HOME / ".gemini" / "antigravity-ide" / "brain",
    "claudecode": _HOME / ".claude" / "projects",
    "codex": _HOME / ".codex",
}

_DEFAULT_CONFIG: Dict[str, Any] = {
    "tools": {
        "antigravity": {
            "path": str(DEFAULT_TOOL_PATHS["antigravity"]),
            "parser": "antigravity",
        },
        "claudecode": {
            "path": str(DEFAULT_TOOL_PATHS["claudecode"]),
            "parser": "claudecode",
            "include_sidechains": False,
        },
        "codex": {
            "path": str(DEFAULT_TOOL_PATHS["codex"]),
            "parser": "codex",
        },
    }
}

_CONFIG_FILE = Path(__file__).parent.parent / "config" / "tools.yaml"


def load_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """Load tool configuration, merging user overrides over built-in defaults."""
    path = config_path or _CONFIG_FILE

    if not path.exists():
        return _deep_copy(_DEFAULT_CONFIG)

    with open(path, "r", encoding="utf-8") as f:
        user_cfg = yaml.safe_load(f) or {}

    config = _deep_copy(_DEFAULT_CONFIG)
    for tool, settings in user_cfg.get("tools", {}).items():
        if tool in config["tools"]:
            config["tools"][tool].update(settings)
        else:
            config["tools"][tool] = settings

    return config


def _deep_copy(obj: Any) -> Any:
    import copy
    return copy.deepcopy(obj)
