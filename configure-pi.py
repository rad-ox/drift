#!/usr/bin/env python3
"""Render the installer-owned component path; source-linked extensions stay inert."""
import json
from pathlib import Path
import sys

source, target, component = sys.argv[1:]
text = Path(source).read_text(encoding="utf-8")
marker = 'const releaseDirectory = "";'
if text.count(marker) != 1:
    raise SystemExit("drift: Pi release component marker missing or ambiguous")
directory = str(Path(component).resolve()) if Path(component).is_dir() else ""
Path(target).write_text(
    text.replace(marker, f"const releaseDirectory = {json.dumps(directory)};"), encoding="utf-8",
)
