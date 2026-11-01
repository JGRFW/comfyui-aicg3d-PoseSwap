"""Build the self-contained, compressed portrait library shipped with the plugin.

Usage:
    python scripts/build_bundled_portraits.py --source <portrait-gallery/library> --destination portraits

The source images are CC0 according to the original site, which also asks users
to avoid redistributing the image data. This helper is for project maintainers
who have made their own distribution decision and must preserve attribution.
"""
import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from PIL import Image, ImageOps

FULL_SIZE = (768, 960)
FULL_QUALITY = 86
THUMB_SIZE = (360, 450)
THUMB_QUALITY = 78


def convert(source, destination, size, quality):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and destination.stat().st_mtime_ns >= source.stat().st_mtime_ns:
        with Image.open(destination) as existing:
            return existing.size
    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
        image.thumbnail(size, Image.Resampling.LANCZOS)
        temporary = destination.with_name(destination.name + ".tmp")
        image.save(temporary, "WEBP", quality=quality, method=6)
        width, height = image.size
    temporary.replace(destination)
    return width, height


def process(source_full, target_full, target_thumb):
    full_size = convert(source_full, target_full, FULL_SIZE, FULL_QUALITY)
    thumb_size = convert(target_full, target_thumb, THUMB_SIZE, THUMB_QUALITY)
    return full_size, thumb_size


def build(source, destination, workers=8):
    source = source.resolve()
    destination = destination.resolve()
    index_path = source / "data" / "portrait-zh.json"
    if not index_path.is_file():
        raise FileNotFoundError(f"缺少索引：{index_path}")
    records = json.loads(index_path.read_text(encoding="utf-8"))
    tasks = []
    rows = []
    for entry in records:
        portrait_id = entry.get("id")
        if not isinstance(portrait_id, str) or not portrait_id:
            continue
        source_full = source / "img" / "full" / f"{portrait_id}.png"
        if not source_full.is_file():
            continue
        target_full = destination / "img" / "full" / f"{portrait_id}.webp"
        target_thumb = destination / "img" / "thumb" / f"{portrait_id}.webp"
        row = dict(entry)
        row["full"] = f"img/full/{portrait_id}.webp"
        row["thumb"] = f"img/thumb/{portrait_id}.webp"
        row["thumb_w"] = THUMB_SIZE[0]
        row["thumb_h"] = THUMB_SIZE[1]
        rows.append((row, source_full, target_full, target_thumb))

    dimensions = {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {}
        for row, source_full, target_full, target_thumb in rows:
            futures[executor.submit(process, source_full, target_full, target_thumb)] = row["id"]
        for future in as_completed(futures):
            portrait_id = futures[future]
            full_size, thumb_size = future.result()
            dimensions[portrait_id] = {"full": full_size, "thumb": thumb_size}

    output_rows = []
    for row, source_full, target_full, target_thumb in rows:
        portrait_id = row["id"]
        width, height = dimensions[portrait_id]["full"]
        thumb_width, thumb_height = dimensions[portrait_id]["thumb"]
        row["w"] = width
        row["h"] = height
        row["thumb_w"] = thumb_width
        row["thumb_h"] = thumb_height
        row["bytes"] = target_full.stat().st_size
        output_rows.append(row)

    data_dir = destination / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "portrait-zh.json").write_text(
        json.dumps(output_rows, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    source_meta = json.loads((source / "data" / "meta-zh.json").read_text(encoding="utf-8"))
    source_meta.update(
        {
            "bundled": True,
            "bundled_snapshot": "compressed-webp",
            "full_max": list(FULL_SIZE),
            "thumb_max": list(THUMB_SIZE),
            "records": len(output_rows),
            "license_notice": (
                "原站标注 CC0 1.0，并请求避免直接再分发图片数据。"
                "本目录是随插件分发的压缩副本，署名与来源链接必须保留。"
            ),
        }
    )
    (data_dir / "meta-zh.json").write_text(json.dumps(source_meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (destination / "SOURCE.json").write_text(
        json.dumps(
            {
                "source": "https://ai-portrait-gallery.pages.dev/",
                "author": "あぎ (@agi_aibusi)",
                "author_url": "https://x.com/agi_aibusi",
                "snapshot_date": "2026-10-30",
                "license": "CC0 1.0",
                "license_url": "https://creativecommons.org/publicdomain/zero/1.0/deed.zh",
                "bundled_compressed_copy": True,
                "full_max": list(FULL_SIZE),
                "thumb_max": list(THUMB_SIZE),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {
        "records": len(output_rows),
        "full_bytes": sum((destination / row["full"]).stat().st_size for row in output_rows),
        "thumb_bytes": sum((destination / row["thumb"]).stat().st_size for row in output_rows),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.destination, args.workers), ensure_ascii=False, indent=2))
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 JGRFW
