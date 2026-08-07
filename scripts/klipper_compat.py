#!/usr/bin/env python3
"""Capability-based Klipper compatibility probe for Ace Pro Control Center."""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple


MIN_PYTHON = (3, 8)
MIN_PYSERIAL = (3, 4)

# These are runtime capabilities consumed by ace_driver, not release-version
# proxies. Method tokens may be implemented by any class in vendor forks.
CORE_REQUIREMENTS: Mapping[str, Tuple[str, ...]] = {
    "klippy.py": (
        "method:get_reactor",
        "method:lookup_object",
        "method:register_event_handler",
        "method:add_object",
        "method:load_object",
        "method:get_start_args",
    ),
    "configfile.py": (
        "method:get_printer",
        "method:get_name",
        "method:get",
        "method:getsection",
        "method:get_prefix_sections",
        "attribute:fileconfig",
    ),
    "reactor.py": (
        "method:register_timer",
        "method:unregister_timer",
        "method:monotonic|attribute:monotonic",
        "method:pause",
    ),
    "gcode.py": (
        "method:register_command",
        "method:run_script_from_command",
    ),
}

EXTRA_REQUIREMENTS: Mapping[str, Tuple[str, ...]] = {
    "filament_switch_sensor.py": ("function:load_config_prefix", "method:get_status"),
    "print_stats.py": ("function:load_config", "method:get_status"),
}

RUNTIME_PROBE = r'''
import importlib
import json
import os
import re
import sys

repo = os.path.realpath(sys.argv[1])
result = {
    "ok": True,
    "python": {
        "version": ".".join(str(item) for item in sys.version_info[:3]),
        "minimum": "3.8",
        "compatible": sys.version_info[:2] >= (3, 8),
    },
    "pyserial": {"version": None, "minimum": "3.4", "compatible": False},
    "ace_driver": {"importable": False, "origin": None, "from_repo": False},
    "errors": [],
}
if not result["python"]["compatible"]:
    result["errors"].append("Python 3.8 or newer is required")

try:
    serial = importlib.import_module("serial")
    try:
        from importlib import metadata
        serial_version = metadata.version("pyserial")
    except Exception:
        serial_version = getattr(serial, "VERSION", getattr(serial, "__version__", None))
    result["pyserial"]["version"] = None if serial_version is None else str(serial_version)
    numbers = tuple(int(item) for item in re.findall(r"\d+", str(serial_version or ""))[:2])
    numbers = numbers + (0,) * (2 - len(numbers))
    result["pyserial"]["compatible"] = numbers[:2] >= (3, 4)
    if not result["pyserial"]["compatible"]:
        result["errors"].append("pyserial 3.4 or newer is required")
except Exception as exc:
    result["errors"].append("pyserial is unavailable: %s" % exc)

try:
    sys.path.insert(0, repo)
    ace_driver = importlib.import_module("ace_driver")
    origin = os.path.realpath(getattr(ace_driver, "__file__", ""))
    try:
        from_repo = os.path.commonpath([origin, repo]) == repo
    except (ValueError, OSError):
        from_repo = False
    result["ace_driver"].update(
        {"importable": True, "origin": origin or None, "from_repo": from_repo}
    )
    if not from_repo:
        result["errors"].append("ace_driver was not imported from --repo")
except Exception as exc:
    result["errors"].append("ace_driver import failed: %s" % exc)

result["ok"] = not result["errors"]
print(json.dumps(result, sort_keys=True))
'''


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        print(json.dumps({"compatible": False, "errors": [message]}, sort_keys=True))
        raise SystemExit(2)


def _source_root(klipper_home: Path) -> Path:
    candidates = (klipper_home / "klippy", klipper_home)
    for candidate in candidates:
        if (candidate / "klippy.py").is_file():
            return candidate.resolve()
    return (klipper_home / "klippy").resolve()


def _tokens(tree: ast.AST) -> Set[str]:
    tokens: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            parent_is_class = getattr(node, "_ace_parent_is_class", False)
            kind = "method" if parent_is_class else "function"
            tokens.add("%s:%s" % (kind, node.name))
        elif isinstance(node, ast.ClassDef):
            tokens.add("class:%s" % node.name)
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    setattr(child, "_ace_parent_is_class", True)
        elif isinstance(node, ast.Attribute):
            tokens.add("attribute:%s" % node.attr)
    # ast.walk visits a class's children after the ClassDef, so method markers
    # above are visible before those FunctionDef nodes are processed.
    return tokens


def _inspect_file(path: Path, required: Iterable[str]) -> Dict[str, Any]:
    required_tokens = list(required)
    result: Dict[str, Any] = {
        "path": str(path),
        "exists": path.is_file(),
        "parseable": False,
        "required_tokens": required_tokens,
        "missing_tokens": required_tokens,
        "compatible": False,
    }
    if not path.is_file():
        result["error"] = "required source file is missing"
        return result
    try:
        source = path.read_text(encoding="utf-8")
        found = _tokens(ast.parse(source, filename=str(path)))
    except (OSError, UnicodeError, SyntaxError) as exc:
        result["error"] = "unable to parse source: %s" % exc
        return result
    missing = [
        requirement
        for requirement in required_tokens
        if not any(token in found for token in requirement.split("|"))
    ]
    result.update(
        {
            "parseable": True,
            "missing_tokens": missing,
            "compatible": not missing,
        }
    )
    return result


def _literal_version_labels(path: Path) -> Dict[str, str]:
    labels: Dict[str, str] = {}
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeError, SyntaxError):
        return labels
    accepted = {"version", "__version__", "klipper_version", "VERSION"}
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        value = node.value
        if not isinstance(value, ast.Constant):
            continue
        literal = value.value
        if not isinstance(literal, (str, int, float)):
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id in accepted:
                labels[target.id] = str(literal)
    return labels


def _version_metadata(klipper_home: Path, source_root: Path) -> Dict[str, Any]:
    source_labels: Dict[str, str] = _literal_version_labels(source_root / "klippy.py")
    for candidate in (
        klipper_home / ".version",
        source_root / ".version",
        klipper_home / "VERSION",
        source_root / "VERSION",
    ):
        try:
            value = candidate.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            continue
        if value:
            source_labels[str(candidate.relative_to(klipper_home))] = value.splitlines()[0]

    git: Dict[str, Any] = {"available": False, "describe": None, "commit": None}
    commands = {
        "describe": ["git", "-C", str(klipper_home), "describe", "--tags", "--always", "--dirty"],
        "commit": ["git", "-C", str(klipper_home), "rev-parse", "HEAD"],
    }
    for key, command in commands.items():
        try:
            completed = subprocess.run(
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, check=False, timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            break
        if completed.returncode == 0 and completed.stdout.strip():
            git[key] = completed.stdout.strip()
            git["available"] = True
    return {"git": git, "source_labels": source_labels, "used_for_compatibility": False}


def _runtime_check(
    executable: str,
    repo: Path,
    runner: Callable[..., Any] = subprocess.run,
) -> Dict[str, Any]:
    command = [str(executable), "-c", RUNTIME_PROBE, str(repo.resolve())]
    try:
        completed = runner(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, check=False, timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "executable": str(executable), "errors": [str(exc)]}
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "runtime probe failed"
        return {
            "ok": False,
            "executable": str(executable),
            "returncode": completed.returncode,
            "errors": [message],
        }
    try:
        result = json.loads(completed.stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "executable": str(executable),
            "errors": ["runtime probe returned invalid JSON: %s" % exc],
        }
    result["executable"] = str(executable)
    return result


def check_compatibility(
    klipper_home: Path,
    repo: Path,
    python_executable: Optional[str] = None,
    skip_runtime_check: bool = False,
    runtime_runner: Callable[..., Any] = subprocess.run,
) -> Dict[str, Any]:
    klipper_home = Path(klipper_home).expanduser().resolve()
    repo = Path(repo).expanduser().resolve()
    source_root = _source_root(klipper_home)
    core = {
        name: _inspect_file(source_root / name, requirements)
        for name, requirements in CORE_REQUIREMENTS.items()
    }
    extras_root = source_root / "extras"
    extras = {
        name: _inspect_file(extras_root / name, requirements)
        for name, requirements in EXTRA_REQUIREMENTS.items()
    }

    errors: List[str] = []
    for group, values in (("core", core), ("extras", extras)):
        for name, result in values.items():
            if not result["compatible"]:
                detail = result.get("error") or "missing API tokens: %s" % ", ".join(result["missing_tokens"])
                errors.append("%s/%s: %s" % (group, name, detail))

    if not (repo / "ace_driver" / "__init__.py").is_file():
        errors.append("--repo does not contain ace_driver/__init__.py")

    runtime: Dict[str, Any]
    if skip_runtime_check:
        runtime = {"skipped": True, "ok": None, "reason": "--skip-runtime-check"}
    else:
        runtime = _runtime_check(python_executable or sys.executable, repo, runtime_runner)
        if not runtime.get("ok"):
            errors.extend("runtime: %s" % item for item in runtime.get("errors", ["probe failed"]))

    return {
        "schema_version": 1,
        "compatible": not errors,
        "compatibility_basis": "capability-probe",
        "klipper_home": str(klipper_home),
        "source_root": str(source_root),
        "repo": str(repo),
        "core": core,
        "extras": extras,
        "runtime": runtime,
        "version": _version_metadata(klipper_home, source_root),
        "errors": errors,
    }


def _parser() -> JsonArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--klipper-home", required=True, type=Path)
    common.add_argument("--repo", required=True, type=Path)
    common.add_argument("--python", dest="python_executable")
    common.add_argument("--skip-runtime-check", action="store_true")
    parser = JsonArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("check", parents=[common], help="check compatibility")
    subparsers.add_parser("report", parents=[common], help="report compatibility details")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = check_compatibility(
            args.klipper_home,
            args.repo,
            python_executable=args.python_executable,
            skip_runtime_check=args.skip_runtime_check,
        )
    except Exception as exc:  # Keep installer-facing failures machine readable.
        result = {"compatible": False, "errors": ["compatibility probe failed: %s" % exc]}
    result["command"] = args.command
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.get("compatible") else 1


if __name__ == "__main__":
    raise SystemExit(main())
