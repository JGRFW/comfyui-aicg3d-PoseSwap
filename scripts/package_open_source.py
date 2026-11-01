#!/usr/bin/env python3
"""Build an open-source release archive for this ComfyUI custom node."""
from __future__ import annotations

import argparse
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSET_DIRS = ("library", "garments", "portraits")
SKIP_DIRS = {".git", "__pycache__", "dist", "release", ".pytest_cache"}
SKIP_SUFFIXES = {
    ".pyc", ".pyo", ".log", ".zip", ".safetensors", ".ckpt", ".pt", ".pth",
}
REQUIRED_TEXT_FILES = (
    "LICENSE",
    "AUTHORS.md",
    "README.md",
    "LEGAL_AND_SAFETY.md",
    "THIRD_PARTY_NOTICES.md",
    "PORTRAIT_LIBRARY_NOTICE.md",
    "MODEL_REQUIREMENTS.md",
    "RELEASE_CHECKLIST.md",
    "CONTRIBUTING.md",
)


def is_asset_path(relative: Path) -> bool:
    return bool(relative.parts) and relative.parts[0] in ASSET_DIRS


def iter_files(include_assets: bool):
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if any(part in SKIP_DIRS for part in relative.parts):
            continue
        if path.suffix.lower() in SKIP_SUFFIXES:
            continue
        if is_asset_path(relative) and not include_assets:
            continue
        yield path, relative


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--with-local-assets",
        action="store_true",
        help="Include library/, garments/, and portraits/ from the local checkout.",
    )
    parser.add_argument(
        "--acknowledge-license-risk",
        action="store_true",
        help="Required with --with-local-assets after manually reviewing the asset notices.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
    )
    args = parser.parse_args()

    if args.with_local_assets and not args.acknowledge_license_risk:
        parser.error(
            "--with-local-assets requires --acknowledge-license-risk. "
            "The bundled third-party asset licenses are not cleared for public redistribution."
        )
    if args.output is None:
        package_name = (
            "comfyui-aicg3d-PoseSwap-with-uncleared-assets.zip"
            if args.with_local_assets
            else "comfyui-aicg3d-PoseSwap-code-only.zip"
        )
        args.output = ROOT / "dist" / package_name

    missing = [name for name in REQUIRED_TEXT_FILES if not (ROOT / name).is_file()]
    if missing:
        raise SystemExit(f"Missing required release files: {', '.join(missing)}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "package": args.output.name,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "code_license": "MIT",
        "third_party_assets_included": args.with_local_assets,
        "asset_directories": list(ASSET_DIRS),
        "model_weights_included": False,
    }

    selected = list(iter_files(args.with_local_assets))
    oversized = [(relative, path.stat().st_size) for path, relative in selected if path.stat().st_size >= 100 * 1024 * 1024]
    if oversized:
        details = ", ".join(f"{relative} ({size} bytes)" for relative, size in oversized)
        raise SystemExit(f"GitHub single-file limit risk: {details}")

    with zipfile.ZipFile(args.output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr("PACKAGE_MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for path, relative in selected:
            archive.write(path, relative.as_posix())

    print(f"Created: {args.output}")
    print(f"Files: {len(selected)}")
    if args.with_local_assets:
        print("WARNING: third-party image assets are included; do not publish without verified rights.")
    else:
        print("Third-party image libraries were excluded. Set the three AICG3D_*_LIBRARY variables for local use.")


if __name__ == "__main__":
    main()
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 JGRFW
