"""Local portrait reference index and compressed preview cache.

The default ``portraits/`` directory may contain a compressed local WebP copy.
For code-only releases, users should provide their own lawfully obtained copy
through ``AICG3D_PORTRAIT_LIBRARY``.
"""
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent
LIBRARY_ENV = "AICG3D_PORTRAIT_LIBRARY"
CACHE_ENV = "AICG3D_PORTRAIT_CACHE"

SOURCE_URL = "https://ai-portrait-gallery.pages.dev/"
AUTHOR_NAME = "あぎ"
AUTHOR_URL = "https://x.com/agi_aibusi"
PROJECT_URL = "https://github.com/wangweihong/comfyui-portrait-gallery"
LICENSE_NAME = "CC0 1.0"
LICENSE_URL = "https://creativecommons.org/publicdomain/zero/1.0/deed.zh"
SNAPSHOT_DATE = "2026-10-30"

SOURCE_LABEL = "AI モデル顔データベース（AI Portrait Gallery）"
REDISTRIBUTION_NOTE = (
    "原站标注 CC0 1.0，并请求避免直接再分发图片数据本身。"
    "本插件按项目分发需要包含压缩后的本地副本，并保留署名、原站与许可链接。"
    "公开再发布或商业使用前，请自行核对原站最新规则并承担合规责任。"
)
DISCLAIMER = (
    "本功能是独立的本地索引与工作流工具，不是原作者官方项目，也不代表原作者背书。"
    "人像为 AI 生成的虚构人物；不得用于冒充真实人物、侵犯肖像权、隐私权、名誉权，"
    "不得用于违法或违背公序良俗的用途。生成结果、素材使用方式及合规责任由使用者自行承担。"
)
LEGAL_NOTE = "以上为来源与使用提示，不构成法律意见。"

ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
THUMB_SIZE = (360, 450)
THUMB_QUALITY = 78


def _comfy_user_directory():
    try:
        import folder_paths

        return Path(folder_paths.get_user_directory())
    except Exception:
        return ROOT.parent.parent / "user"


def _library_candidates():
    env_path = os.environ.get(LIBRARY_ENV)
    if env_path:
        yield Path(env_path).expanduser()
    yield ROOT / "portraits"
    yield ROOT / "portraits" / "library"
    yield ROOT.parent / "comfyui-portrait-gallery" / "library"
    yield ROOT.parent / "comfyui-portrait-gallery-main" / "comfyui-portrait-gallery" / "library"


@lru_cache(maxsize=1)
def library_root():
    for candidate in _library_candidates():
        try:
            root = candidate.resolve()
        except OSError:
            continue
        if (root / "data" / "portrait-zh.json").is_file():
            return root
    raise FileNotFoundError(
        "人像图库缺失。请把 comfyui-portrait-gallery 的 library 目录链接为插件的 portraits/，"
        f"或设置环境变量 {LIBRARY_ENV} 指向该目录。"
    )


def cache_root():
    configured = os.environ.get(CACHE_ENV)
    root = Path(configured).expanduser() if configured else _comfy_user_directory() / "aicg3d_portrait_cache"
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def thumb_path(portrait_id):
    if not ID_RE.fullmatch(str(portrait_id)):
        raise ValueError("无效人像 ID")
    bundled = (library_root() / "img" / "thumb" / f"{portrait_id}.webp").resolve()
    if bundled.is_relative_to(library_root()) and bundled.is_file():
        return bundled
    return cache_root() / "thumbs" / f"{portrait_id}.webp"


@lru_cache(maxsize=4)
def _read_records(path, modified, size):
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("人像图库索引格式错误")
    records = []
    for entry in rows:
        if not isinstance(entry, dict):
            continue
        portrait_id = entry.get("id")
        if not isinstance(portrait_id, str) or not ID_RE.fullmatch(portrait_id):
            continue
        if entry.get("section") not in ("face", "styling"):
            continue
        row = {
            "id": portrait_id,
            "section": entry["section"],
            "section_zh": entry.get("section_zh", "正脸参考" if entry["section"] == "face" else "造型参考"),
            "hair_zh": entry.get("hair_zh", ""),
            "style_zh": entry.get("style_zh", ""),
            "title": entry.get("title") or entry.get("style_zh") or portrait_id,
            "w": entry.get("w", 0),
            "h": entry.get("h", 0),
            "bytes": entry.get("bytes", 0),
            "search": entry.get("search", ""),
            "thumb_url": f"/aicg3d_pose/portraits/thumb/{portrait_id}.webp",
            "source_url": SOURCE_URL,
            "source_label": SOURCE_LABEL,
            "author_name": AUTHOR_NAME,
            "author_url": AUTHOR_URL,
            "license_name": LICENSE_NAME,
            "license_url": LICENSE_URL,
        }
        records.append(row)
    if not records:
        raise ValueError("人像图库索引为空")
    return records


def records():
    root = library_root()
    source = root / "data" / "portrait-zh.json"
    stat = source.stat()
    return _read_records(str(source), stat.st_mtime_ns, stat.st_size)


def metadata():
    rows = records()
    return {
        "total": len(rows),
        "sections": {
            "face": sum(row["section"] == "face" for row in rows),
            "styling": sum(row["section"] == "styling" for row in rows),
        },
        "snapshot_date": SNAPSHOT_DATE,
        "source_url": SOURCE_URL,
        "author_name": AUTHOR_NAME,
        "author_url": AUTHOR_URL,
        "license_name": LICENSE_NAME,
        "license_url": LICENSE_URL,
        "redistribution_note": REDISTRIBUTION_NOTE,
        "disclaimer": DISCLAIMER,
        "legal_note": LEGAL_NOTE,
    }


def portrait(portrait_id):
    if not isinstance(portrait_id, str) or not ID_RE.fullmatch(portrait_id):
        raise ValueError("无效人像 ID")
    for row in records():
        if row["id"] == portrait_id:
            return row
    raise ValueError(f"未知人像 ID：{portrait_id}")


def full_path(portrait_id):
    root = library_root()
    row = portrait(portrait_id)
    for suffix in (".webp", ".png"):
        target = (root / "img" / "full" / f"{portrait_id}{suffix}").resolve()
        if not target.is_relative_to(root):
            raise ValueError("人像原图路径越出图库目录")
        if target.is_file():
            return target
    raise FileNotFoundError(f"人像原图缺失：{portrait_id}")


def source_thumb_path(portrait_id):
    root = library_root()
    target = (root / "img" / "thumb" / f"{portrait_id}.webp").resolve()
    if not target.is_relative_to(root):
        raise ValueError("人像缩略图路径越出图库目录")
    if not target.is_file():
        return full_path(portrait_id)
    return target


def ensure_thumb(portrait_id):
    target = thumb_path(portrait_id)
    source = source_thumb_path(portrait_id)
    if target == source or (target.is_file() and target.stat().st_mtime_ns >= source.stat().st_mtime_ns):
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
        image.thumbnail(THUMB_SIZE, Image.Resampling.LANCZOS)
        temporary = target.with_name(target.name + ".tmp")
        image.save(temporary, "WEBP", quality=THUMB_QUALITY, method=6)
    temporary.replace(target)
    return target


def build_cache(workers=8, limit=None):
    rows = records()
    if limit is not None:
        rows = rows[:limit]
    completed = 0
    failures = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {executor.submit(ensure_thumb, row["id"]): row["id"] for row in rows}
        for future in as_completed(futures):
            portrait_id = futures[future]
            try:
                future.result()
                completed += 1
            except Exception as exc:
                failures.append((portrait_id, str(exc)))
    return {"completed": completed, "failed": len(failures), "failures": failures[:20]}


def load_image(portrait_id):
    """Load the selected original PNG as a ComfyUI IMAGE tensor."""
    import numpy as np
    import torch

    with Image.open(full_path(portrait_id)) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGBA")
        background = Image.new("RGBA", image.size, "white")
        image = Image.alpha_composite(background, image).convert("RGB")
        tensor = torch.from_numpy(np.asarray(image).astype(np.float32) / 255.0).unsqueeze(0)
    return tensor


def description(portrait_id):
    row = portrait(portrait_id)
    return " / ".join(value for value in (row["section_zh"], row["hair_zh"], row["style_zh"]) if value)


def attribution(portrait_id):
    row = portrait(portrait_id)
    return (
        f"{row['source_label']} / 原作者 {row['author_name']} / {row['author_url']} / "
        f"{row['license_name']} / {row['license_url']}"
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Build compressed portrait previews outside the plugin directory.")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    print(json.dumps(build_cache(workers=args.workers, limit=args.limit), ensure_ascii=False, indent=2))
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 JGRFW
