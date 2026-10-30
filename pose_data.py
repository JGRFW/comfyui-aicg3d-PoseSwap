"""ComfyUI-AICG3D-pose 自带的姿势图库数据访问层。

本插件完全独立：图库（data/pose-zh.json + img/ + thumbs/）随插件目录一起分发，
不依赖任何外部插件。别人拷贝整个插件目录即可获得相同图库。
"""
import json
import os
from functools import lru_cache
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent
LIBRARY = Path(os.environ.get("AICG3D_POSE_LIBRARY", ROOT / "library")).resolve()


@lru_cache(maxsize=1)
def records():
    source = LIBRARY / "data" / "pose-zh.json"
    if not source.is_file():
        raise FileNotFoundError(
            f"姿势图库缺失：{source}。请确认插件目录完整（含 library/data/pose-zh.json），"
            "或设置环境变量 AICG3D_POSE_LIBRARY 指向图库根目录。"
        )
    return json.loads(source.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def index():
    return {row["id"]: row for row in records()}


def pose(pose_id):
    try:
        return index()[pose_id]
    except KeyError:
        raise ValueError(f"未知姿势 ID：{pose_id}") from None


def asset(kind, filename):
    """图库内图片安全路径校验：只允许 img/thumbs 下的原文件名。"""
    if kind not in ("img", "thumbs") or Path(filename).name != filename or "\\" in filename:
        raise ValueError("无效图片路径")
    pose_id, suffix = os.path.splitext(filename)
    row = pose(pose_id)
    expected = row["原图" if kind == "img" else "缩略图"]
    relative = Path(kind) / filename
    target = (LIBRARY / relative).resolve()
    if expected != relative.as_posix() or not target.is_relative_to(LIBRARY):
        raise ValueError("图片不在图库中")
    if not target.is_file():
        raise FileNotFoundError(f"图片缺失：{relative}。请检查插件目录完整性（library/{kind}/）。")
    return target


def load_pose_image(library, pose_id):
    """把姿势原图读成 ComfyUI IMAGE 张量 [1,H,W,3]。"""
    row = find_pose(library, pose_id)
    if row is None:
        raise ValueError(f"未知姿势 ID：{pose_id}（请通过图库浏览按钮重新选择）")
    img_rel = row.get("原图")
    if not img_rel:
        raise ValueError(f"姿势 {pose_id} 缺少原图字段")
    path = (library / img_rel).resolve()
    if not path.is_relative_to(library.resolve()) or not path.is_file():
        raise FileNotFoundError(f"姿势原图缺失：{img_rel}。请检查插件 library/img/ 目录完整性。")
    with Image.open(path) as source:
        img = ImageOps.exif_transpose(source).convert("RGBA")
        background = Image.new("RGBA", img.size, "white")
        img = Image.alpha_composite(background, img).convert("RGB")
        tensor = torch.from_numpy(np.asarray(img).astype(np.float32) / 255.0).unsqueeze(0)
    return tensor


def pose_description(library, pose_id):
    row = find_pose(library, pose_id)
    if row is None:
        return ""
    return " / ".join(row.get(k, "") for k in ("体系", "分类", "姿势名称", "角度"))


def find_pose(library, pose_id):
    for row in load_catalog(library):
        if row.get("id") == pose_id:
            return row
    return None


def load_catalog(library):
    source = library / "data" / "pose-zh.json"
    if not source.is_file():
        raise FileNotFoundError(f"姿势图库缺失：{source}")
    return json.loads(source.read_text(encoding="utf-8"))
