# SPDX-License-Identifier: MIT
# Copyright (c) 2026 JGRFW
"""Configure an external portrait library without editing ComfyUI launch flags."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import portrait_data  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="Path to comfyui-portrait-gallery/library")
    parser.add_argument("--clear", action="store_true", help="Remove the saved portrait-library path")
    parser.add_argument("--status", action="store_true", help="Only print the current library status")
    args = parser.parse_args()

    if args.clear:
        portrait_data.POINTER_FILE.unlink(missing_ok=True)
        portrait_data.library_root.cache_clear()
    elif args.source:
        portrait_data.configure_library(args.source)
    elif not args.status:
        parser.error("use --source <library> or --clear")

    print(json.dumps(portrait_data.library_status(), ensure_ascii=False, indent=2))
    if not portrait_data.library_status().get("available"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
