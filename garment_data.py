"""comfyui-aicg3d-PoseSwap 自带的服装图库数据访问层。

本插件完全独立：服装图库（garments/data/garment.json + garments/img/*.webp）
随插件目录一起分发，不依赖 nvzhuang 或任何外部插件。别人拷贝整个插件目录
即可获得相同服装图库。
"""
import json
import os
from functools import lru_cache
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent
GARMENTS = Path(os.environ.get("AICG3D_GARMENT_LIBRARY", ROOT / "garments")).resolve()


@lru_cache(maxsize=1)
def records():
    source = GARMENTS / "data" / "garment.json"
    if not source.is_file():
        raise FileNotFoundError(
            f"服装图库缺失：{source}。请确认插件目录完整（含 garments/data/garment.json）。"
        )
    return json.loads(source.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def index():
    return {row["id"]: row for row in records().get("records", [])}


def garment(garment_id):
    try:
        return index()[garment_id]
    except KeyError:
        raise ValueError(f"未知服装 ID：{garment_id}") from None


def asset(filename):
    """服装图库内图片安全路径校验：只允许 img/ 下原文件名（ID.webp）。"""
    if Path(filename).name != filename or "\\" in filename:
        raise ValueError("无效图片路径")
    garment_id, suffix = os.path.splitext(filename)
    row = garment(garment_id)
    expected = row.get("img")
    relative = Path("img") / filename
    target = (GARMENTS / relative).resolve()
    if expected != relative.as_posix() or not target.is_relative_to(GARMENTS):
        raise ValueError("图片不在服装图库中")
    if not target.is_file():
        raise FileNotFoundError(f"图片缺失：{relative}。请检查插件目录完整性（garments/img/）。")
    return target


def load_garment_image(garment_id):
    """把服装图读成 ComfyUI IMAGE 张量 [1,H,W,3]。"""
    row = garment(garment_id)
    img_rel = row.get("img")
    if not img_rel:
        raise ValueError(f"服装 {garment_id} 缺少图片字段")
    path = (GARMENTS / img_rel).resolve()
    if not path.is_relative_to(GARMENTS.resolve()) or not path.is_file():
        raise FileNotFoundError(f"服装图缺失：{img_rel}。请检查插件 garments/img/ 目录完整性。")
    with Image.open(path) as source:
        img = ImageOps.exif_transpose(source).convert("RGBA")
        background = Image.new("RGBA", img.size, "white")
        img = Image.alpha_composite(background, img).convert("RGB")
        tensor = torch.from_numpy(np.asarray(img).astype(np.float32) / 255.0).unsqueeze(0)
    return tensor


def garment_description(garment_id):
    row = garment(garment_id)
    return " / ".join(str(row.get(k, "")) for k in ("cat_cn", "desc"))
