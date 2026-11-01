# SPDX-License-Identifier: MIT
# Copyright (c) 2026 JGRFW
"""Report embedded metadata in bundled image assets before publishing."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIRS = ("library/img", "library/thumbs", "garments/img", "portraits/img")
IMAGE_SUFFIXES = {".webp", ".jpg", ".jpeg", ".png"}
SENSITIVE_INFO_KEYS = {"exif", "xmp", "xml", "comment", "comments", "author", "copyright"}


def summarize_image(path: Path) -> dict:
    with Image.open(path) as image:
        exif = image.getexif()
        sensitive_info = {
            key: str(value)[:500]
            for key, value in image.info.items()
            if key.lower() in SENSITIVE_INFO_KEYS
        }
        return {
            "width": image.width,
            "height": image.height,
            "format": image.format,
            "exif_tags": len(exif),
            "sensitive_info": sensitive_info,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, help="Directories to scan")
    args = parser.parse_args()
    roots = [path.resolve() for path in (args.paths or [ROOT / item for item in DEFAULT_DIRS])]

    scanned = 0
    findings = []
    for directory in roots:
        if not directory.is_dir():
            continue
        for path in directory.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            scanned += 1
            try:
                summary = summarize_image(path)
            except Exception as exc:
                findings.append({"file": str(path), "error": str(exc)})
                continue
            if summary["exif_tags"] or summary["sensitive_info"]:
                findings.append({"file": str(path), **summary})

    print(json.dumps({
        "scanned_images": scanned,
        "images_with_sensitive_metadata": len(findings),
        "findings": findings,
    }, ensure_ascii=False, indent=2))
    if findings:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
