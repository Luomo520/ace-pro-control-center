#!/usr/bin/env python3
"""Build a validated Ace Pro Control Center deployment bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tarfile
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, Optional

from validate_release import is_retired_hardware_config_path, validate_repo


RELEASE_ID_RE = re.compile(r"^\d{8}_\d{6}$")
SOURCE_NAME = "ace-pro-control-center"
SOURCE_ARCHIVE_NAME = "Ace-Pro-Control-Center.tar.gz"
SOURCE_ENTRIES = (
    "ace_driver",
    "config",
    "docs",
    "frontend",
    "installer",
    "klipper_extras",
    "moonraker",
    "scripts",
    "tests",
    "wiki",
    "LICENSE",
    "MANIFEST.in",
    "pyproject.toml",
    "README.md",
    "THIRD_PARTY_NOTICES.md",
)
EXCLUDED_PARTS = {
    ".git",
    ".pytest_cache",
    "__pycache__",
    "node_modules",
}


def _archive_filter(info: tarfile.TarInfo) -> Optional[tarfile.TarInfo]:
    parts = Path(info.name).parts
    if any(part in EXCLUDED_PARTS or part.startswith(".pytest-tmp") for part in parts):
        return None
    if info.name.endswith((".pyc", ".pyo")):
        return None
    if is_retired_hardware_config_path(info.name):
        raise ValueError(
            f"refusing retired hardware config in release archive: {info.name}"
        )
    if info.isdir():
        info.mode = 0o755
    elif info.isfile():
        info.mode = 0o755 if Path(info.name).suffix == ".sh" else 0o644
    return info


def _validate_source_archive_members(path: Path) -> None:
    with tarfile.open(path, "r:*") as archive:
        retired = sorted(
            member.name
            for member in archive.getmembers()
            if is_retired_hardware_config_path(member.name)
        )
    if retired:
        raise ValueError(
            "source archive contains retired hardware config: " + ", ".join(retired)
        )


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _has_asset_marker(paths: Iterable[Path], marker: str) -> bool:
    needle = marker.encode("utf-8")
    return any(needle in path.read_bytes() for path in paths if path.is_file())


def _parse_tests(values: Iterable[str]) -> Dict[str, str]:
    tests: Dict[str, str] = {}
    for value in values:
        name, separator, result = value.partition("=")
        if not separator or not name.strip() or not result.strip():
            raise ValueError("--test must use NAME=RESULT")
        tests[name.strip()] = result.strip()
    return tests


def _driver_version(repo: Path) -> str:
    source = (repo / "ace_driver" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'(?m)^__version__\s*=\s*"([^"]+)"\s*$', source)
    if match is None:
        raise ValueError("ace_driver.__version__ is not declared")
    return match.group(1)


def _fluidd_version(fluidd_dist: Path) -> str:
    version_file = fluidd_dist / ".version"
    if version_file.is_file():
        value = version_file.read_text(encoding="utf-8").strip()
        value = value[1:] if value.startswith("v") else value
        if value:
            return value
    release_info = fluidd_dist / "release_info.json"
    if release_info.is_file():
        value = str(json.loads(release_info.read_text(encoding="utf-8")).get("version") or "")
        value = value.strip()
        value = value[1:] if value.startswith("v") else value
        if value:
            return value
    raise ValueError("Fluidd dist does not declare its version")


def package_release(
    repo: Path,
    fluidd_dist: Path,
    output: Path,
    release_id: str,
    change: str,
    tests: Dict[str, str],
) -> Path:
    if not RELEASE_ID_RE.fullmatch(release_id):
        raise ValueError("release id must use YYYYMMDD_HHMMSS")
    errors = validate_repo(repo, require_frontend=True)
    if errors:
        raise ValueError("invalid release tree: " + "; ".join(errors))
    if not (fluidd_dist / "index.html").is_file():
        raise ValueError("Fluidd dist is missing index.html")
    assets = fluidd_dist / "assets"
    card_assets = list(assets.glob("AceV3Card-*"))
    if not any(path.suffix == ".js" for path in card_assets):
        raise ValueError("Fluidd dist is missing AceV3Card JavaScript")
    if not list(assets.glob("AcePro-*.js")):
        raise ValueError("Fluidd dist is missing AcePro JavaScript")
    if not _has_asset_marker(card_assets, "acepro-slot-card__spool"):
        raise ValueError("Fluidd dist does not contain the V2 slot-card marker")
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)

    source_archive = output / SOURCE_ARCHIVE_NAME
    with tarfile.open(source_archive, "w:gz", compresslevel=9) as archive:
        for entry in SOURCE_ENTRIES:
            path = repo / entry
            if not path.exists():
                raise ValueError(f"release entry is missing: {path}")
            archive.add(path, arcname=entry, recursive=True, filter=_archive_filter)
    _validate_source_archive_members(source_archive)

    fluidd_archive = output / "fluidd-dist.tar.gz"
    with tarfile.open(fluidd_archive, "w:gz", compresslevel=9) as archive:
        for path in sorted(fluidd_dist.iterdir(), key=lambda item: item.name):
            archive.add(path, arcname=path.name, recursive=True, filter=_archive_filter)

    artifacts = []
    for path in (source_archive, fluidd_archive):
        artifacts.append(
            {
                "name": path.name,
                "bytes": path.stat().st_size,
                "sha256": _hash(path),
            }
        )
    manifest = {
        "schema_version": 1,
        "release_id": release_id,
        "created": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": SOURCE_NAME,
        "driver": _driver_version(repo),
        "fluidd": _fluidd_version(fluidd_dist),
        "change": change,
        "tests": tests,
        "validation": {
            "release_tree": "passed",
            "fluidd_dist": "passed",
            "slot_card_marker": "passed",
        },
        "artifacts": artifacts,
    }
    manifest_path = output / "deploy-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--fluidd-dist", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--change", required=True)
    parser.add_argument("--test", action="append", default=[])
    args = parser.parse_args()
    try:
        manifest = package_release(
            args.repo.resolve(),
            args.fluidd_dist.resolve(),
            args.output.resolve(),
            args.release_id,
            args.change,
            _parse_tests(args.test),
        )
    except ValueError as exc:
        parser.error(str(exc))
    print(f"release package ready: {manifest.parent}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
