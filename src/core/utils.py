"""
core/utils.py — config loader + logging setup.
"""

import logging
import os
import sys
from pathlib import Path
from typing import Optional, Union

try:
    import yaml
except ImportError:
    yaml = None


def load_config(config_path=None, **_):
    # type: (Optional[Union[str, Path]]) -> dict
    """
    Load config.yaml. Falls back to environment variables for secrets.
    Returns a flat dict with all keys.
    """
    cfg = {}  # type: dict

    # Try YAML first
    paths_to_try = [config_path, "config.yaml", "config.yml"] if config_path else ["config.yaml", "config.yml"]
    for p in paths_to_try:
        if p and Path(p).exists() and yaml:
            with open(p, encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            break

    # Layer in environment variables (GitHub Actions secrets)
    env_map = {
        "SERPAPI_KEY":    ("api", "serpapi_key"),
        "OLLAMA_API_KEY": ("api", "ollama_api_key"),
        "USER_AGENT":     ("api", "user_agent"),
    }
    for env_var, (section, key) in env_map.items():
        val = os.environ.get(env_var)
        if val:
            cfg.setdefault(section, {})[key] = val

    return cfg


def get(cfg, *keys, **kwargs):
    # type: (dict, ...) -> object
    """Safe nested dict getter: get(cfg, 'api', 'serpapi_key')"""
    default = kwargs.get("default", None)
    node = cfg
    for k in keys:
        if not isinstance(node, dict):
            return default
        node = node.get(k, default)
    return node


def setup_logging(level="INFO", log_file=None):
    # type: (str, Optional[str]) -> None
    handlers = [logging.StreamHandler(sys.stdout)]
    if log_file:
        handlers.append(logging.FileHandler(log_file))
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        handlers=handlers,
    )
