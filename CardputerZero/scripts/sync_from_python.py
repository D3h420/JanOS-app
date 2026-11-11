#!/usr/bin/env python3
"""Generate the Cardputer Zero command contract from the Python application.

This script is the synchronization boundary between the reference Python
controller and the native Cardputer application. It combines the declarative catalog from
``projectzero_commands.py`` with command call sites discovered in
``JanOS_app.py``.  Dynamic call sites are preserved as explicit manual-porting
items; they are never silently claimed as synchronized.

The output is deterministic.  ``--check`` does not write anything and exits
non-zero when the checked-in artifact differs from the current Python sources.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Dict, Iterable, List, Optional, Tuple


SCHEMA_VERSION = 1
CALL_METHODS = {
    "send_command": "send",
    "run_simple_command": "oneshot",
    "monitor_command": "stream",
    "prompt_and_run_command": "prompt",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_catalog(path: Path):
    spec = importlib.util.spec_from_file_location("janos_ssot_catalog", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolves the defining module through sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _attribute_name(call: ast.Call) -> Optional[str]:
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _literal_command(node: ast.AST) -> Optional[str]:
    """Return the statically known command root, including f-string prefixes."""
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "strip"
        and not node.args
        and not node.keywords
    ):
        node = node.func.value
    value: Optional[str] = None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        value = node.value
    elif isinstance(node, ast.JoinedStr):
        pieces: List[str] = []
        for item in node.values:
            if isinstance(item, ast.Constant) and isinstance(item.value, str):
                pieces.append(item.value)
            else:
                break
        value = "".join(pieces)
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    root = stripped.split(None, 1)[0]
    return root if root.replace("_", "a").isalnum() else None


def _call_owner(parents: Dict[ast.AST, ast.AST], node: ast.AST) -> str:
    current: Optional[ast.AST] = node
    while current is not None:
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current.name
        current = parents.get(current)
    return "<module>"


def _scan_python_commands(path: Path) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    parents: Dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent

    discovered: List[Dict[str, Any]] = []
    unresolved: List[Dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        method = _attribute_name(node)
        if method not in CALL_METHODS or not node.args:
            continue
        owner = _call_owner(parents, node)
        command = _literal_command(node.args[0])
        entry = {
            "file": path.name,
            "line": node.lineno,
            "function": owner,
            "transport": CALL_METHODS[method],
        }
        if command:
            entry["command"] = command
            discovered.append(entry)
        else:
            try:
                expression = ast.unparse(node.args[0])
            except Exception:
                expression = "<unparseable>"
            entry["expression"] = expression
            entry["reason"] = "dynamic command expression requires a Cardputer handler review"
            unresolved.append(entry)

    key = lambda item: (item["command"], item["file"], item["line"], item["function"])
    discovered.sort(key=key)
    unresolved.sort(key=lambda item: (item["file"], item["line"], item["function"]))
    return discovered, unresolved


def _catalog_entries(module) -> Iterable[Dict[str, Any]]:
    groups = dict(module.COMMAND_GROUPS)
    groups.update(getattr(module, "SHARED_COMMAND_GROUPS", {}))
    for group, specs in groups.items():
        for spec in specs:
            yield {
                "command": spec.command,
                "group": group,
                "label": spec.label,
                "arguments": spec.arguments,
                "stream": bool(spec.stream),
                "confirm": bool(spec.confirm),
            }


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def build_manifest(root: Path) -> Dict[str, Any]:
    app_path = root / "JanOS_app.py"
    core_path = root / "janos_core.py"
    catalog_path = root / "projectzero_commands.py"
    module = _load_catalog(catalog_path)
    callsites, unresolved = _scan_python_commands(app_path)

    commands: Dict[str, Dict[str, Any]] = {}
    for item in _catalog_entries(module):
        command = item["command"]
        record = commands.setdefault(
            command,
            {
                "command": command,
                "label": command.replace("_", " ").title(),
                "arguments": "",
                "groups": [],
                "stream": False,
                "confirm": False,
                "sources": [],
                "python_handlers": [],
            },
        )
        record["label"] = item["label"]
        record["arguments"] = item["arguments"]
        record["stream"] = item["stream"]
        record["confirm"] = item["confirm"]
        record["groups"].append(item["group"])
        record["sources"].append("projectzero_commands.py")

    for command in module.FILE_COMMANDS:
        record = commands.setdefault(
            command,
            {
                "command": command,
                "label": command.replace("_", " ").title(),
                "arguments": "",
                "groups": [],
                "stream": False,
                "confirm": False,
                "sources": [],
                "python_handlers": [],
            },
        )
        record["groups"].append("SD / binary transfer")
        record["sources"].append("projectzero_commands.py:FILE_COMMANDS")

    for site in callsites:
        command = site["command"]
        record = commands.setdefault(
            command,
            {
                "command": command,
                "label": command.replace("_", " ").title(),
                "arguments": "",
                "groups": ["Python workflows"],
                "stream": False,
                "confirm": False,
                "sources": [],
                "python_handlers": [],
            },
        )
        source = f"{site['file']}:{site['line']}"
        if source not in record["sources"]:
            record["sources"].append(source)
        handler = {
            "function": site["function"],
            "transport": site["transport"],
        }
        if handler not in record["python_handlers"]:
            record["python_handlers"].append(handler)
        if site["transport"] == "stream":
            record["stream"] = True

    normalized_commands = []
    for command in sorted(commands):
        record = commands[command]
        record["groups"] = sorted(set(record["groups"]))
        record["sources"] = sorted(set(record["sources"]))
        record["python_handlers"].sort(key=lambda item: (item["function"], item["transport"]))
        normalized_commands.append(record)

    contract = {
        "schema_version": SCHEMA_VERSION,
        "commands": normalized_commands,
        "manual_porting": unresolved,
    }
    fingerprint = _sha256(_canonical_bytes(contract))
    return {
        **contract,
        "fingerprint": f"sha256:{fingerprint}",
        "source_fingerprints": {
            "JanOS_app.py": f"sha256:{_sha256(app_path.read_bytes())}",
            "janos_core.py": f"sha256:{_sha256(core_path.read_bytes())}",
            "projectzero_commands.py": f"sha256:{_sha256(catalog_path.read_bytes())}",
        },
    }


def render_manifest(manifest: Dict[str, Any]) -> str:
    return json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail when generated output is stale")
    parser.add_argument("--output", type=Path, help="override generated JSON path")
    args = parser.parse_args(argv)

    root = _repo_root()
    output = args.output or root / "CardputerZero" / "generated" / "command_catalog.json"
    rendered = render_manifest(build_manifest(root))

    if args.check:
        if not output.exists():
            print(f"missing generated artifact: {output}", file=sys.stderr)
            return 1
        actual = output.read_text(encoding="utf-8")
        if actual != rendered:
            print(
                "Cardputer Zero command catalog is stale; run "
                "CardputerZero/scripts/sync_from_python.py",
                file=sys.stderr,
            )
            return 1
        print(f"command catalog is synchronized ({len(json.loads(rendered)['commands'])} commands)")
        return 0

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    print(f"generated {output} ({len(json.loads(rendered)['commands'])} commands)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

