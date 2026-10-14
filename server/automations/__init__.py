"""Registry of the user's connected automations.

Each automation is a folder `automations/<id>/` with an `automation.yaml` (see docs/automations.md).
The folder location can be changed with the FLOWHAUS_AUTOMATIONS_DIR environment variable.
Configs are re-read when they change on disk, so an agent can edit them while the app runs.

Types:
  github_actions  a GitHub Actions workflow, read with the `gh` CLI      (server/automations/github_actions.py)
  folder_runs     a script that writes one folder per run                (server/automations/folder_runs.py)
  python          custom code: `adapter.py` with create(config, folder)  (see docs/automations.md)
"""

from __future__ import annotations

import importlib.util
import os
import re
import threading
from pathlib import Path

import yaml

from server.automations.base import Automation
from server.automations.folder_runs import FolderRunsAutomation
from server.automations.github_actions import GitHubActionsAutomation

ROOT = Path(__file__).resolve().parent.parent.parent
ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,60}$")
TYPES = {"github_actions": GitHubActionsAutomation, "folder_runs": FolderRunsAutomation}


def automations_dir() -> Path:
    return Path(os.environ.get("FLOWHAUS_AUTOMATIONS_DIR") or ROOT / "automations").expanduser().resolve()


class LoadError(Exception):
    pass


def load_one(folder: Path) -> Automation:
    path = folder / "automation.yaml"
    try:
        config = yaml.safe_load(path.read_text()) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise LoadError(f"{path}: {exc}") from exc
    if not isinstance(config, dict):
        raise LoadError(f"{path}: expected a mapping at the top level")
    config.setdefault("id", folder.name)
    if not ID.match(str(config["id"])):
        raise LoadError(f"{path}: id must be lowercase letters, digits and dashes")
    kind = config.get("type")
    if kind == "python":
        module_path = folder / config.get("module", "adapter.py")
        spec = importlib.util.spec_from_file_location(f"flowhaus_automation_{config['id'].replace('-', '_')}", module_path)
        if not spec or not spec.loader:
            raise LoadError(f"{module_path}: cannot import")
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
            automation = module.create(config, folder)
        except Exception as exc:  # user code: report, never crash the app
            raise LoadError(f"{module_path}: {type(exc).__name__}: {exc}") from exc
        if not isinstance(automation, Automation):
            raise LoadError(f"{module_path}: create() must return a server.automations.base.Automation")
        return automation
    if kind not in TYPES:
        raise LoadError(f"{path}: type must be one of {', '.join([*TYPES, 'python'])}, got {kind!r}")
    try:
        return TYPES[kind](config, folder)
    except (KeyError, TypeError, ValueError, re.error) as exc:
        raise LoadError(f"{path}: {type(exc).__name__}: {exc}") from exc


_lock = threading.Lock()
_cache: tuple[tuple, dict[str, Automation], dict[str, str]] = ((), {}, {})


def _fingerprint(base: Path) -> tuple:
    if not base.is_dir():
        return ()
    items = []
    for p in sorted(base.glob("*/automation.yaml")):
        files = [p, *(p.parent.glob("*.py"))]
        items.append(tuple((str(f), f.stat().st_mtime_ns) for f in files))
    return tuple(items)


def load_all() -> tuple[dict[str, Automation], dict[str, str]]:
    """(automations by id, load errors by folder). Cached until a config file changes."""
    global _cache
    base = automations_dir()
    fp = _fingerprint(base)
    with _lock:
        if fp == _cache[0] and fp:
            return _cache[1], _cache[2]
        found, errors = {}, {}
        for path in sorted(base.glob("*/automation.yaml")) if base.is_dir() else []:
            try:
                a = load_one(path.parent)
            except LoadError as exc:
                errors[path.parent.name] = str(exc)
                continue
            if a.id in found:
                errors[path.parent.name] = f"duplicate id '{a.id}'"
                continue
            found[a.id] = a
        _cache = (fp, found, errors)
        return found, errors


def all_automations() -> dict[str, Automation]:
    return load_all()[0]


def read_only_paths() -> list[Path]:
    return [p for a in all_automations().values() if (p := a.readable_code_path())]


def private_paths() -> list[Path]:
    return [p for a in all_automations().values() for p in a.private_paths()]
