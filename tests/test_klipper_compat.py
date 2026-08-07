from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_module():
    name = "ace_v3_klipper_compat_tests"
    spec = importlib.util.spec_from_file_location(
        name, PROJECT_ROOT / "scripts" / "klipper_compat.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


compat = _load_module()


SOURCES = {
    "klippy.py": """
class Printer:
    def get_reactor(self): pass
    def lookup_object(self): pass
    def register_event_handler(self): pass
    def add_object(self): pass
    def load_object(self): pass
    def get_start_args(self): pass
""",
    "configfile.py": """
class ConfigWrapper:
    def __init__(self): self.fileconfig = None
    def get_printer(self): pass
    def get_name(self): pass
    def get(self): pass
    def getsection(self): pass
    def get_prefix_sections(self): pass
""",
    "reactor.py": """
class Reactor:
    def __init__(self): self.monotonic = lambda: 0.0
    def register_timer(self): pass
    def unregister_timer(self): pass
    def pause(self): pass
""",
    "gcode.py": """
class GCodeDispatch:
    def register_command(self): pass
    def run_script_from_command(self): pass
""",
}

EXTRAS = {
    "filament_switch_sensor.py": """
def load_config_prefix(config): pass
class Sensor:
    def get_status(self): pass
""",
    "print_stats.py": """
def load_config(config): pass
class PrintStats:
    def get_status(self): pass
""",
}


def make_klipper(tmp_path: Path) -> Path:
    root = tmp_path / "klipper"
    source = root / "klippy"
    extras = source / "extras"
    extras.mkdir(parents=True)
    for name, value in SOURCES.items():
        (source / name).write_text(value, encoding="utf-8")
    for name, value in EXTRAS.items():
        (extras / name).write_text(value, encoding="utf-8")
    return root


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    package = repo / "ace_driver"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("__version__ = 'test'\n", encoding="utf-8")
    return repo


def runtime_result(*, python_ok=True, serial_ok=True, import_ok=True):
    errors = []
    if not python_ok:
        errors.append("Python 3.8 or newer is required")
    if not serial_ok:
        errors.append("pyserial is unavailable")
    if not import_ok:
        errors.append("ace_driver import failed")
    return {
        "ok": not errors,
        "python": {"version": "3.7.17" if not python_ok else "3.10.12", "compatible": python_ok},
        "pyserial": {"version": None if not serial_ok else "3.4", "compatible": serial_ok},
        "ace_driver": {"importable": import_ok, "from_repo": import_ok},
        "errors": errors,
    }


def fake_runner(payload):
    def run(_command, **_kwargs):
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
    return run


def test_compatible_capabilities_and_runtime(tmp_path):
    klipper = make_klipper(tmp_path)
    repo = make_repo(tmp_path)

    result = compat.check_compatibility(
        klipper, repo, python_executable="klipper-python",
        runtime_runner=fake_runner(runtime_result()),
    )

    assert result["compatible"] is True
    assert result["compatibility_basis"] == "capability-probe"
    assert result["runtime"]["executable"] == "klipper-python"
    assert result["version"]["used_for_compatibility"] is False
    assert all(item["compatible"] for item in result["core"].values())
    assert all(item["compatible"] for item in result["extras"].values())


def test_missing_api_token_is_incompatible(tmp_path):
    klipper = make_klipper(tmp_path)
    repo = make_repo(tmp_path)
    gcode = klipper / "klippy" / "gcode.py"
    gcode.write_text(gcode.read_text(encoding="utf-8").replace("run_script_from_command", "run_script"), encoding="utf-8")

    result = compat.check_compatibility(klipper, repo, skip_runtime_check=True)

    assert result["compatible"] is False
    assert result["core"]["gcode.py"]["missing_tokens"] == ["method:run_script_from_command"]
    assert any("core/gcode.py" in item for item in result["errors"])


def test_vendor_reactor_method_form_is_also_compatible(tmp_path):
    klipper = make_klipper(tmp_path)
    repo = make_repo(tmp_path)
    reactor = klipper / "klippy" / "reactor.py"
    reactor.write_text(
        reactor.read_text(encoding="utf-8").replace(
            "def __init__(self): self.monotonic = lambda: 0.0",
            "def monotonic(self): return 0.0",
        ),
        encoding="utf-8",
    )

    result = compat.check_compatibility(klipper, repo, skip_runtime_check=True)

    assert result["compatible"] is True


def test_old_python_is_reported_by_injected_runtime(tmp_path):
    result = compat.check_compatibility(
        make_klipper(tmp_path), make_repo(tmp_path),
        runtime_runner=fake_runner(runtime_result(python_ok=False)),
    )

    assert result["compatible"] is False
    assert result["runtime"]["python"]["compatible"] is False
    assert any("Python 3.8" in item for item in result["errors"])


def test_missing_pyserial_is_reported_by_injected_runtime(tmp_path):
    result = compat.check_compatibility(
        make_klipper(tmp_path), make_repo(tmp_path),
        runtime_runner=fake_runner(runtime_result(serial_ok=False)),
    )

    assert result["compatible"] is False
    assert result["runtime"]["pyserial"]["compatible"] is False
    assert any("pyserial" in item for item in result["errors"])


def test_no_git_repository_is_report_only_not_incompatible(tmp_path):
    result = compat.check_compatibility(
        make_klipper(tmp_path), make_repo(tmp_path), skip_runtime_check=True
    )

    assert result["compatible"] is True
    assert result["version"]["git"] == {
        "available": False, "describe": None, "commit": None
    }


def test_cli_check_outputs_json_and_nonzero_on_error(tmp_path, capsys):
    klipper = make_klipper(tmp_path)
    repo = make_repo(tmp_path)
    (klipper / "klippy" / "reactor.py").unlink()

    exit_code = compat.main([
        "check", "--klipper-home", str(klipper), "--repo", str(repo),
        "--skip-runtime-check",
    ])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert output["command"] == "check"
    assert output["compatible"] is False


def test_cli_report_uses_real_runtime_and_repo_import(tmp_path, capsys):
    klipper = make_klipper(tmp_path)
    repo = make_repo(tmp_path)

    exit_code = compat.main([
        "report", "--klipper-home", str(klipper), "--repo", str(repo),
        "--python", sys.executable,
    ])
    output = json.loads(capsys.readouterr().out)

    expected = 0 if output["runtime"]["pyserial"]["compatible"] else 1
    assert exit_code == expected
    assert output["command"] == "report"
    assert output["runtime"]["ace_driver"]["from_repo"] is True
