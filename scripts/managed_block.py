#!/usr/bin/env python3
"""Add, replace, or remove an explicitly delimited configuration block."""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path
from typing import Optional


MARKERS = {
    "printer": (
        "# >>> ACE Driver V3 managed include >>>",
        "# <<< ACE Driver V3 managed include <<<",
        "[include ace.cfg]",
    ),
    "moonraker": (
        "# >>> ACE Driver V3 managed component >>>",
        "# <<< ACE Driver V3 managed component <<<",
        "[ace_status]",
    ),
}

COMPATIBLE_LINES = {
    "printer": re.compile(r"^[ \t]*\[include[ \t]+ace\.cfg\][ \t]*$", re.MULTILINE | re.IGNORECASE),
    "moonraker": re.compile(r"^[ \t]*\[ace_status\][ \t]*$", re.MULTILINE | re.IGNORECASE),
}

SAVE_CONFIG_MARKER = re.compile(
    r"^#\*# <[-]+ SAVE_CONFIG [-]+>[ \t]*$", re.MULTILINE
)


def replace_block(
    text: str,
    start: str,
    end: str,
    body: Optional[str],
    *,
    insert_before: Optional[re.Pattern[str]] = None,
) -> str:
    start_index = text.find(start)
    end_index = text.find(end)
    if (start_index < 0) != (end_index < 0):
        raise ValueError("managed block has only one boundary marker")
    if start_index >= 0:
        if end_index < start_index:
            raise ValueError("managed block boundary markers are reversed")
        end_index += len(end)
        while end_index < len(text) and text[end_index] in "\r\n":
            end_index += 1
        prefix = text[:start_index].rstrip()
        suffix = text[end_index:].strip("\r\n")
        text = "\n\n".join(part for part in (prefix, suffix) if part)
    text = text.rstrip()
    if body is not None:
        block = f"{start}\n{body}\n{end}"
        marker = insert_before.search(text) if insert_before is not None else None
        if marker is None:
            text = f"{text}\n\n{block}" if text else block
        else:
            prefix = text[: marker.start()].rstrip()
            suffix = text[marker.start() :].lstrip("\r\n")
            text = "\n\n".join(part for part in (prefix, block, suffix) if part)
    return text.rstrip() + "\n"


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("ensure", "remove", "validate"))
    parser.add_argument("kind", choices=tuple(MARKERS))
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    start, end, body = MARKERS[args.kind]
    text = args.path.read_text(encoding="utf-8") if args.path.exists() else ""
    try:
        if args.action in {"ensure", "validate"}:
            text = COMPATIBLE_LINES[args.kind].sub("", text)
        result = replace_block(
            text,
            start,
            end,
            body if args.action in {"ensure", "validate"} else None,
            insert_before=SAVE_CONFIG_MARKER if args.kind == "printer" else None,
        )
    except ValueError as exc:
        parser.error(str(exc))
    if args.action != "validate":
        write_atomic(args.path, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
