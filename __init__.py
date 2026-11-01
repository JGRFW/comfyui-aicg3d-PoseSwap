"""comfyui-aicg3d-PoseSwap: 完全独立的「选姿势/选服装 → Qwen 换姿/换装」插件。

零外部插件依赖：
- 姿势图库（library/）与服装图库（garments/）均随插件目录分发
- 人像图库（portraits/）随插件分发 768×960 WebP 压缩版与浏览缩略图
- 姿势图库 / 服装图库浏览页面（web/gallery.html / web/garment_gallery.html）
  与 /aicg3d_pose/* 路由由本插件自带
 - 人像图库页面（web/portrait_gallery.html）与选择节点同样由本插件自带
- PoseQwen21SequentialEdit 在一个节点内顺序执行换头像、换姿势、换服饰，并按阶段推送节点内预览
- 换姿节点只需 ComfyUI 原生 Qwen Image 2.1 节点（ComfyUI 0.43+）与 models/ 权重
- 换装节点只需 ComfyUI 原生 Qwen-Image-Edit-2511 节点（TextEncodeQwenImageEditPlus /
  FluxKontext* / ModelSamplingAuraFlow / CFGNorm）与 models/ 权重

一条线连接：
  [PoseQwen21PoseSelect 姿势姿态控制] --pose_image--> [PoseQwen21 姿态换姿生成]
  [PoseQwen21GarmentSelect 服装选择]   --garment_image--> [PoseQwen21PoseSwap 换装生成（enable 开关）]
  [PoseQwen21PortraitSelect 换头换脸参考] --portrait_image--> 换脸/换头身份参考
"""
import hashlib
import os
import time
from pathlib import Path
import asyncio

import folder_paths
import nodes
import comfy.samplers
from aiohttp import web
from server import PromptServer
from comfy_extras.nodes_qwen import TextEncodeQwenImage21, QwenImage21Cache, TextEncodeQwenImageEditPlus
from comfy_extras.nodes_flux import FluxKontextImageScale, FluxKontextMultiReferenceLatentMethod
from comfy_extras.nodes_cfg import CFGNorm
from comfy_extras.nodes_model_advanced import ModelSamplingAuraFlow
from comfy_extras.nodes_custom_sampler import (
    CFGGuider, KSamplerSelect, ManualSigmas, RandomNoise, SamplerCustomAdvanced,
)

QWEN21_TURBO_SIGMAS = "1.0, 0.978453, 0.95418, 0.926626, 0.89508, 0.845148, 0.704534, 0.414568, 0"

from . import pose_data
from . import garment_data
from . import portrait_data

# ---------------------------------------------------------------------------
# 模型缓存：内置加载器节点每次调用无状态，这里自己做缓存避免重复加载。
# ---------------------------------------------------------------------------
_MODEL_CACHE = {}


def _cache_unet(name):
    key = ("unet", name)
    if key not in _MODEL_CACHE:
        _MODEL_CACHE[key] = nodes.UNETLoader().load_unet(name, "default")[0]
    return _MODEL_CACHE[key].clone()


def _cache_clip(name):
    key = ("clip", name)
    if key not in _MODEL_CACHE:
        _MODEL_CACHE[key] = nodes.CLIPLoader().load_clip(name, "qwen_image")[0]
    return _MODEL_CACHE[key]


def _cache_vae(name):
    key = ("vae", name)
    if key not in _MODEL_CACHE:
        _MODEL_CACHE[key] = nodes.VAELoader().load_vae(name)[0]
    return _MODEL_CACHE[key]


def _apply_lora(model, lora_name, strength):
    if not lora_name or strength == 0:
        return model
    return nodes.LoraLoaderModelOnly().load_lora_model_only(model, lora_name, strength)[0]


DEFAULT_PROMPT = (
    "Reproduce the EXACT pose, limb angles, body orientation and camera viewpoint "
    "shown in Picture 1. Picture 1 is the only source for pose and body placement. "
    "Picture 2 is the only source for the person's identity and complete outfit: "
    "keep the EXACT same person, face, hairstyle, body proportions, top, bottom, "
    "legwear, footwear, colors, fabric, patterns and accessories, background and "
    "lighting as in Picture 2. If Picture 2 is barefoot, keep bare feet. If Picture 2 "
    "has socks or tights without shoes, keep exactly those and add no shoes. If "
    "Picture 2 has shoes, keep exactly those shoes. Never invent shoes, socks, boots, "
    "extra clothing or accessories that are not visible in Picture 2. Do NOT alter, "
    "replace, remove, recolor or redraw the outfit from Picture 2. Do not copy the "
    "line drawing, mannequin shape or any annotations from Picture 1."
)

# 换装提示词：完整套装（含鞋袜）替换；服装图库 description 会追加到提示词末尾。
DEFAULT_SWAP_PROMPT = (
    "Full-outfit virtual try-on. Edit Picture 1 so the adult woman wears the COMPLETE "
    "outfit shown in Picture 2. Picture 2 is the sole and exact reference for every "
    "clothing component: top, bottom or skirt, belt, legwear and footwear. Replace "
    "the source clothing, socks or tights and shoes with the matching items in "
    "Picture 2. If Picture 2 shows different shoes, the original shoes must be "
    "completely removed and replaced, not retained or merged. If Picture 2 has no "
    "footwear, keep the original footwear exactly. Keep the same identity, face, "
    "hairstyle, body proportions, pose, background and lighting. Do not invent extra "
    "shoes, accessories or clothing. Preserve garment color, pattern, material, trim, "
    "silhouette. Copy the footwear from Picture 2 with its exact color, straps, "
    "platform, sole and heel; do not substitute a generic shoe or a different shoe "
    "color. Photorealistic, both feet and shoes clearly visible. Output only the final "
    "photograph."
)

DEFAULT_FACE_PROMPT = (
    "Edit Picture 1 by replacing only the person's head, facial identity and "
    "hairstyle with the head and hairstyle shown in Picture 2. Preserve Picture 1 "
    "body, pose, clothing, shoes, background, framing, lighting and photographic "
    "style. Match Picture 2 face shape, facial features, skin tone and hair. Do not "
    "copy Picture 2 clothing, body, background or framing. Output one coherent "
    "photorealistic image."
)

def _run_qwen21_edit_stage(image_1, image_2, prompt, unet_name, clip_name,
                              vae_name, width, height, seed, steps,
                              sampler_name, scheduler, cfg):
    """Run one Qwen Image 2.1 edit pass at an explicit output size."""
    model = QwenImage21Cache.execute(
        _cache_unet(unet_name), "auto", "default",
    ).result[0]
    clip = _cache_clip(clip_name)
    vae = _cache_vae(vae_name)
    positive, negative, _ = TextEncodeQwenImage21.execute(
        clip, prompt, "", vae, max(width, height),
        {"image_1": image_1, "image_2": image_2},
    ).result
    latent = nodes.EmptyLatentImage().generate(width, height, 1)[0]
    latent = nodes.KSampler().sample(
        model, seed, steps, cfg, sampler_name, scheduler,
        positive, negative, latent, 1.0,
    )[0]
    return nodes.VAEDecode().decode(vae, latent)[0]


def _run_qwen21_edit_with_model(model, clip, vae, image_1, image_2, prompt,
                                  width, height, seed, steps, sampler_name,
                                  scheduler, cfg):
    model = QwenImage21Cache.execute(model, "auto", "default").result[0]
    positive, negative, _ = TextEncodeQwenImage21.execute(
        clip, prompt, "", vae, max(width, height),
        {"image_1": image_1, "image_2": image_2},
    ).result
    latent = nodes.EmptyLatentImage().generate(width, height, 1)[0]
    latent = nodes.KSampler().sample(
        model, seed, steps, cfg, sampler_name, scheduler,
        positive, negative, latent, 1.0,
    )[0]
    return nodes.VAEDecode().decode(vae, latent)[0]


def _run_qwen21_turbo_edit_with_model(model, clip, vae, image_1, image_2,
                                        prompt, width, height, seed):
    model = QwenImage21Cache.execute(model, "auto", "default").result[0]
    positive, negative, _ = TextEncodeQwenImage21.execute(
        clip, prompt, "", vae, max(width, height),
        {"image_1": image_1, "image_2": image_2},
    ).result
    latent = nodes.EmptyLatentImage().generate(width, height, 1)[0]
    guider = CFGGuider.execute(model, positive, negative, 1.0).result[0]
    noise = RandomNoise.execute(seed).result[0]
    sampler = KSamplerSelect.execute("euler").result[0]
    sigmas = ManualSigmas.execute(QWEN21_TURBO_SIGMAS).result[0]
    latent = SamplerCustomAdvanced.execute(
        noise, guider, sampler, sigmas, latent,
    ).result[0]
    return nodes.VAEDecode().decode(vae, latent)[0]


def _run_qwen21_pose_with_model(model, clip, vae, person_image, pose_image,
                                 prompt, width, height, seed, steps,
                                 sampler_name, scheduler):
    model = QwenImage21Cache.execute(model, "auto", "default").result[0]
    positive, negative, _ = TextEncodeQwenImage21.execute(
        clip, prompt, "", vae, max(width, height),
        {"image_1": pose_image, "image_2": person_image},
    ).result
    latent = nodes.EmptyLatentImage().generate(width, height, 1)[0]
    latent = nodes.KSampler().sample(
        model, seed, steps, 1.0, sampler_name, scheduler,
        positive, negative, latent, 1.0,
    )[0]
    return nodes.VAEDecode().decode(vae, latent)[0]
def _resolve_output_size(image, width, height):
    source_height = max(1, int(image.shape[1]))
    source_width = max(1, int(image.shape[2]))
    try:
        width = max(0, min(4096, int(width)))
        height = max(0, min(4096, int(height)))
    except (TypeError, ValueError):
        width = height = 0
    if width <= 0 and height <= 0:
        scale = min(1.0, 1344 / max(source_width, source_height))
        width, height = source_width * scale, source_height * scale
    elif width <= 0:
        width = round(height * source_width / source_height)
    elif height <= 0:
        height = round(width * source_height / source_width)
    width = max(64, min(4096, round(width / 64) * 64))
    height = max(64, min(4096, round(height / 64) * 64))
    return width, height


def _send_stage_preview(image, unique_id, stage):
    try:
        import numpy as np
        from PIL import Image
        array = (image[0].detach().cpu().clamp(0, 1).numpy() * 255).astype(np.uint8)
        filename = f"aicg3d_stage_{unique_id}_{stage}_{time.time_ns()}.png"
        path = os.path.join(folder_paths.get_temp_directory(), filename)
        Image.fromarray(array).save(path)
        PromptServer.instance.send_sync("aicg3d-stage-preview", {
            "node_id": str(unique_id),
            "stage": stage,
            "filename": filename,
            "subfolder": "",
            "type": "temp",
        })
    except Exception as exc:
        print(f"[AICG3D-PoseSwap] stage preview failed: {exc}")


def _run_qwen21_turbo_edit_stage(image_1, image_2, prompt, unet_name,
                                   clip_name, vae_name, width, height, seed):
    """Fast 8-step Qwen 2.1 path used by the avatar stage."""
    model = QwenImage21Cache.execute(
        _cache_unet(unet_name), "auto", "default",
    ).result[0]
    clip = _cache_clip(clip_name)
    vae = _cache_vae(vae_name)
    positive, negative, _ = TextEncodeQwenImage21.execute(
        clip, prompt, "", vae, max(width, height),
        {"image_1": image_1, "image_2": image_2},
    ).result
    latent = nodes.EmptyLatentImage().generate(width, height, 1)[0]
    guider = CFGGuider.execute(model, positive, negative, 1.0).result[0]
    noise = RandomNoise.execute(seed).result[0]
    sampler = KSamplerSelect.execute("euler").result[0]
    sigmas = ManualSigmas.execute(QWEN21_TURBO_SIGMAS).result[0]
    latent = SamplerCustomAdvanced.execute(
        noise, guider, sampler, sigmas, latent,
    ).result[0]
    return nodes.VAEDecode().decode(vae, latent)[0]
def _run_qwen21_pose_stage(person_image, pose_image, prompt, unet_name,
                              clip_name, vae_name, lora_name, width, height,
                              seed, steps, sampler_name, scheduler):
    model = _apply_lora(_cache_unet(unet_name), lora_name, 1.0)
    model = QwenImage21Cache.execute(model, "auto", "default").result[0]
    clip = _cache_clip(clip_name)
    vae = _cache_vae(vae_name)
    positive, negative, _ = TextEncodeQwenImage21.execute(
        clip, prompt, "", vae, max(width, height),
        {"image_1": pose_image, "image_2": person_image},
    ).result
    latent = nodes.EmptyLatentImage().generate(width, height, 1)[0]
    latent = nodes.KSampler().sample(
        model, seed, steps, 1.0, sampler_name, scheduler,
        positive, negative, latent, 1.0,
    )[0]
    return nodes.VAEDecode().decode(vae, latent)[0]
def _validate_pose_library():
    try:
        pose_data.records()
        return True
    except FileNotFoundError as exc:
        return str(exc)


def _validate_garment_library():
    try:
        garment_data.records()
        return True
    except FileNotFoundError as exc:
        return str(exc)


# ---------------------------------------------------------------------------
# 节点 B：姿势姿态控制（输出 pose_image 一条线连到生成节点）
# ---------------------------------------------------------------------------
class PoseQwen21PoseSelect:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "pose_id": ("STRING", {
                    "default": "full_sexy_P002_front",
                    "multiline": False,
                    "tooltip": "点击「浏览姿势图库」选择姿势；也可直接输入图库 ID（如 full_sexy_P031_front）。",
                }),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("pose_image", "pose_id", "description")
    FUNCTION = "load_pose"
    CATEGORY = "image/Pose Gallery/Qwen2.1"
    DESCRIPTION = "姿势姿态控制：浏览图库选姿势，输出姿势原图（pose_image）供生成节点使用。"

    @classmethod
    def IS_CHANGED(cls, pose_id):
        return hashlib.sha256(pose_id.encode()).hexdigest()

    @classmethod
    def VALIDATE_INPUTS(cls, **kwargs):
        return _validate_pose_library()

    def load_pose(self, pose_id):
        library = pose_data.LIBRARY
        pose_image = pose_data.load_pose_image(library, pose_id)
        description = pose_data.pose_description(library, pose_id)
        return (pose_image, pose_id, description)


# ---------------------------------------------------------------------------
# 节点 C：服装选择（输出 garment_image 一条线连到换装生成节点）
# ---------------------------------------------------------------------------
class PoseQwen21GarmentSelect:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "garment_id": ("STRING", {
                    "default": "SPR-0001",
                    "multiline": False,
                    "tooltip": "点击「浏览服装图库」选择服装；也可直接输入图库 ID（如 SPR-0001）。",
                }),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("garment_image", "garment_id", "description")
    FUNCTION = "load_garment"
    CATEGORY = "image/Pose Gallery/Qwen2.1"
    DESCRIPTION = "服装选择：浏览内置服装图库选服装，输出服装参考图（garment_image）供换装节点使用。"

    @classmethod
    def IS_CHANGED(cls, garment_id):
        return hashlib.sha256(garment_id.encode()).hexdigest()

    @classmethod
    def VALIDATE_INPUTS(cls, **kwargs):
        return _validate_garment_library()

    def load_garment(self, garment_id):
        garment_image = garment_data.load_garment_image(garment_id)
        description = garment_data.garment_description(garment_id)
        return (garment_image, garment_id, description)


# ---------------------------------------------------------------------------
# 节点 C2：换头换脸参考选择（只读取本地图库，不随插件分发图片）
# ---------------------------------------------------------------------------
class PoseQwen21PortraitSelect:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "portrait_id": ("STRING", {
                    "default": "f71f980dde3",
                    "multiline": False,
                    "tooltip": "点击浏览人像图库选择正脸或造型参考；原图保存在外部本地图库，不随插件分发。",
                }),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("portrait_image", "portrait_id", "description", "attribution")
    FUNCTION = "load_portrait"
    CATEGORY = "image/Pose Gallery/Qwen2.1"
    DESCRIPTION = "换头换脸参考选择：浏览本地人像图库，输出原图、编号、描述与原作者署名。素材来源见图库页面。"

    @classmethod
    def IS_CHANGED(cls, portrait_id):
        path = portrait_data.full_path(portrait_id)
        stat = path.stat()
        return f"{stat.st_mtime_ns}:{stat.st_size}"

    @classmethod
    def VALIDATE_INPUTS(cls, portrait_id):
        try:
            portrait_data.full_path(portrait_id)
        except (ValueError, FileNotFoundError) as exc:
            return str(exc)
        return True

    def load_portrait(self, portrait_id):
        image = portrait_data.load_image(portrait_id)
        return (
            image,
            portrait_id,
            portrait_data.description(portrait_id),
            portrait_data.attribution(portrait_id),
        )


# ---------------------------------------------------------------------------
# 节点 A：姿态换姿生成
# ---------------------------------------------------------------------------
class PoseQwen21:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "person_image": ("IMAGE", {"tooltip": "你生成/加载的人物参考图，将保持身份、服装与画风。请用成人参考图。"}),
                "pose_image": ("IMAGE", {"tooltip": "来自「PoseQwen21PoseSelect 姿势姿态控制」节点的姿势原图（image_1）。"}),
                "prompt": ("STRING", {"default": DEFAULT_PROMPT, "multiline": True,
                                      "tooltip": "姿态迁移提示词。默认无需修改；切换复杂姿势时可补充动作描述。"}),
                "negative_prompt": ("STRING", {"default": "", "multiline": True}),
                "unet_name": (folder_paths.get_filename_list("diffusion_models"), {
                    "default": "qwen/qwen_image_2.1_bf16.safetensors",
                    "tooltip": "Qwen Image 2.1 基础模型。"}),
                "clip_name": (folder_paths.get_filename_list("text_encoders"), {
                    "default": "qwen3vl_8b_bf16.safetensors",
                    "tooltip": "Qwen3-VL 8B 文本与图像编码器（type=qwen_image）。"}),
                "vae_name": (folder_paths.get_filename_list("vae"), {
                    "default": "qwen_image_2.1_vae_bf16.safetensors",
                    "tooltip": "Qwen Image 2.1 配套 VAE。"}),
                "lora_name": (folder_paths.get_filename_list("loras"), {
                    "default": "qwen-image2.1/VNCCS_QI2_PoseStudioV1.1.safetensors",
                    "tooltip": "Qwen2.1 姿态编辑适配器（Pose Studio）。留空则不加载。"}),
                "lora_strength": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 2.0, "step": 0.05}),
                "resolution": ("INT", {"default": 1024, "min": 0, "max": 4096, "step": 32,
                                       "tooltip": "参考图按约 resolution² 像素等比缩放（32 的倍数）。0 保留原尺寸。"}),
                "seed": ("INT", {"default": 20261029, "min": 0, "max": 4294967295, "control_after_generate": True}),
                "steps": ("INT", {"default": 25, "min": 1, "max": 10000}),
                "cfg": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 100.0, "step": 0.1, "round": 0.01}),
                "sampler_name": (comfy.samplers.KSampler.SAMPLERS, {"default": "euler"}),
                "scheduler": (comfy.samplers.KSampler.SCHEDULERS, {"default": "simple"}),
                "denoise": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01}),
                "cache_device": (["auto", "gpu", "cpu", "off"], {"default": "auto"}),
                "cache_dtype": (["default", "int8", "int4"], {"default": "default"}),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("image", "description")
    FUNCTION = "run"
    CATEGORY = "image/Pose Gallery/Qwen2.1"
    DESCRIPTION = "姿态换姿生成：person_image（人物）+ pose_image（姿势）→ Qwen Image 2.1 姿态迁移 → 输出成图。前端即千问 image 2.1。"

    @classmethod
    def IS_CHANGED(cls, person_image, pose_image, seed, **kwargs):
        return hashlib.sha256(str(seed).encode()).hexdigest()

    @classmethod
    def VALIDATE_INPUTS(cls, **kwargs):
        return True

    def run(self, person_image, pose_image, prompt, negative_prompt, unet_name, clip_name,
            vae_name, lora_name, lora_strength, resolution, seed, steps, cfg,
            sampler_name, scheduler, denoise, cache_device, cache_dtype):
        # ---- 参数容错：旧工作流加载到新节点时 widget 值可能错位，统一清洗 ----
        valid_samplers = set(comfy.samplers.KSampler.SAMPLERS)
        valid_schedulers = set(comfy.samplers.KSampler.SCHEDULERS)
        if sampler_name not in valid_samplers:
            sampler_name = "euler"
        if scheduler not in valid_schedulers:
            scheduler = "simple"
        try:
            steps = max(1, min(10000, int(steps)))
        except (TypeError, ValueError):
            steps = 25
        try:
            cfg = float(cfg)
        except (TypeError, ValueError):
            cfg = 1.0
        try:
            denoise = max(0.0, min(1.0, float(denoise)))
        except (TypeError, ValueError):
            denoise = 1.0
        try:
            seed = int(seed) & 0xFFFFFFFF
        except (TypeError, ValueError):
            seed = 0
        try:
            resolution = max(0, min(4096, int(resolution)))
        except (TypeError, ValueError):
            resolution = 1024
        try:
            lora_strength = float(lora_strength)
        except (TypeError, ValueError):
            lora_strength = 1.0
        if cache_device not in ("auto", "gpu", "cpu", "off"):
            cache_device = "auto"
        if cache_dtype not in ("default", "int8", "int4"):
            cache_dtype = "default"

        # 1) 加载并挂载 LoRA
        model = _cache_unet(unet_name)
        model = _apply_lora(model, lora_name, lora_strength)
        cache_out = QwenImage21Cache.execute(model, cache_device, cache_dtype)
        model = cache_out.result[0]

        clip = _cache_clip(clip_name)
        vae = _cache_vae(vae_name)

        # 2) 编码：image_1 = 姿势图，image_2 = 人物图
        encoded = TextEncodeQwenImage21.execute(
            clip, prompt, negative_prompt, vae,
            resolution, {"image_1": pose_image, "image_2": person_image},
        )
        positive, negative, latent = encoded.result

        # 3) 采样 + 解码
        latent = nodes.KSampler().sample(
            model, seed, steps, cfg, sampler_name, scheduler,
            positive, negative, latent, denoise,
        )[0]
        images = nodes.VAEDecode().decode(vae, latent)[0]

        return (images, "")


class PoseQwen21FaceStage:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "person_image": ("IMAGE", {}),
                "portrait_image": ("IMAGE", {}),
                "model": ("MODEL", {}),
                "clip": ("CLIP", {}),
                "vae": ("VAE", {}),
                "enable": ("BOOLEAN", {"default": True,
                    "tooltip": "关闭时直接输出人物底图，不运行换头像。"}),
                "seed": ("INT", {"default": 20261101, "min": 0, "max": 4294967295}),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("换头像结果",)
    FUNCTION = "run"
    CATEGORY = "image/Pose Gallery/Qwen2.1"
    DESCRIPTION = "换头像独立阶段。完成本节点后立即输出预览，再进入换姿势。"

    @classmethod
    def IS_CHANGED(cls, person_image, portrait_image, model, clip, vae,
                   enable, seed, **kwargs):
        return hashlib.sha256(str(seed).encode()).hexdigest()

    def run(self, person_image, portrait_image, model, clip, vae, enable, seed):
        if not enable:
            return (person_image,)
        width, height = _resolve_output_size(person_image, 0, 0)
        image = _run_qwen21_turbo_edit_with_model(
            model, clip, vae, person_image, portrait_image, DEFAULT_FACE_PROMPT,
            width, height, int(seed) & 0xFFFFFFFF,
        )
        return (image,)


class PoseQwen21PoseStage:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "person_image": ("IMAGE", {}),
                "pose_image": ("IMAGE", {}),
                "model": ("MODEL", {}),
                "clip": ("CLIP", {}),
                "vae": ("VAE", {}),
                "enable": ("BOOLEAN", {"default": True,
                    "tooltip": "关闭时直接输出换头像结果，不运行换姿势。"}),
                "seed": ("INT", {"default": 20261029, "min": 0, "max": 4294967295}),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("换姿势结果",)
    FUNCTION = "run"
    CATEGORY = "image/Pose Gallery/Qwen2.1"
    DESCRIPTION = "换姿势独立阶段。完成本节点后立即输出预览，再进入换服饰。"

    @classmethod
    def IS_CHANGED(cls, person_image, pose_image, model, clip, vae,
                   enable, seed, **kwargs):
        return hashlib.sha256(str(seed).encode()).hexdigest()

    def run(self, person_image, pose_image, model, clip, vae, enable, seed):

        if not enable:
            return (person_image,)
        width, height = _resolve_output_size(person_image, 0, 0)
        image = _run_qwen21_pose_with_model(
            model, clip, vae, person_image, pose_image, DEFAULT_PROMPT,
            width, height, int(seed) & 0xFFFFFFFF, 25, "euler", "simple",
        )
        return (image,)


class PoseQwen21OutfitStage:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "person_image": ("IMAGE", {}),
                "garment_image": ("IMAGE", {}),
                "model": ("MODEL", {}),
                "clip": ("CLIP", {}),
                "vae": ("VAE", {}),
                "enable": ("BOOLEAN", {"default": True,
                    "tooltip": "关闭时直接输出换姿势结果。"}),
                "width": ("INT", {"default": 0, "min": 0, "max": 4096, "step": 64,
                    "tooltip": "0 表示保持输入原比例；自定义宽度时按 64 对齐。"}),
                "height": ("INT", {"default": 0, "min": 0, "max": 4096, "step": 64,
                    "tooltip": "0 表示保持输入原比例；自定义高度时按 64 对齐。"}),
                "steps": ("INT", {"default": 20, "min": 1, "max": 100}),
                "sampler_name": (comfy.samplers.KSampler.SAMPLERS, {"default": "euler"}),
                "scheduler": (comfy.samplers.KSampler.SCHEDULERS, {"default": "simple"}),
                "seed": ("INT", {"default": 20261101, "min": 0, "max": 4294967295}),
            },
            "optional": {
                "garment_description": ("STRING", {"forceInput": True}),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("换服饰结果",)
    FUNCTION = "run"
    CATEGORY = "image/Pose Gallery/Qwen2.1"
    DESCRIPTION = "换服饰独立阶段。可调步数、采样器、调度器和自定义宽高。"

    @classmethod
    def IS_CHANGED(cls, person_image, garment_image, enable, width, height,
                   steps, sampler_name, scheduler, seed, model, clip, vae,
                   garment_description="", **kwargs):
        value = repr((enable, width, height, steps, sampler_name, scheduler,
                      seed, garment_description))
        return hashlib.sha256(value.encode()).hexdigest()

    def run(self, person_image, garment_image, model, clip, vae, enable, width,
            height, steps, sampler_name, scheduler, seed,
            garment_description=""):
        if not enable:
            return (person_image,)
        width, height = _resolve_output_size(person_image, width, height)
        description = (garment_description or "").strip()
        prompt = DEFAULT_SWAP_PROMPT
        if description:
            prompt += (
                f" Exact outfit metadata from the garment reference: {description}. "
                "Copy every named garment, legwear and footwear detail exactly."
            )
        if sampler_name not in comfy.samplers.KSampler.SAMPLERS:
            sampler_name = "euler"
        if scheduler not in comfy.samplers.KSampler.SCHEDULERS:
            scheduler = "simple"
        image = _run_qwen21_edit_with_model(
            model, clip, vae, person_image, garment_image, prompt, width, height,
            int(seed) & 0xFFFFFFFF, max(1, min(100, int(steps))),
            sampler_name, scheduler, 2.5,
        )
        return (image,)


class PoseQwen21SequentialEdit:
    @classmethod
    def INPUT_TYPES(cls):
        loras = [""] + folder_paths.get_filename_list("loras")
        return {
            "required": {
                "person_image": ("IMAGE", {}),
                "portrait_image": ("IMAGE", {}),
                "pose_image": ("IMAGE", {}),
                "garment_image": ("IMAGE", {}),
                "enable_face": ("BOOLEAN", {"default": True}),
                "enable_pose": ("BOOLEAN", {"default": True}),
                "enable_outfit": ("BOOLEAN", {"default": True}),
                "width": ("INT", {"default": 0, "min": 0, "max": 4096, "step": 64,
                    "tooltip": "换服饰输出宽度；0 表示保持输入原比例。"}),
                "height": ("INT", {"default": 0, "min": 0, "max": 4096, "step": 64,
                    "tooltip": "换服饰输出高度；0 表示保持输入原比例。"}),
                "steps": ("INT", {"default": 20, "min": 1, "max": 100,
                    "tooltip": "仅用于换服饰阶段。细节不稳定时可提高到 25-30。"}),
                "sampler_name": (comfy.samplers.KSampler.SAMPLERS, {"default": "euler"}),
                "scheduler": (comfy.samplers.KSampler.SCHEDULERS, {"default": "simple"}),
                "seed": ("INT", {"default": 20261101, "min": 0, "max": 4294967295}),
                "face_unet_name": (folder_paths.get_filename_list("diffusion_models"), {
                    "default": "qwen\\qwen_image_2.1_int8_convrot.safetensors"}),
                "face_clip_name": (folder_paths.get_filename_list("text_encoders"), {
                    "default": "qwen3vl_8b_int8_convrot.safetensors"}),
                "pose_unet_name": (folder_paths.get_filename_list("diffusion_models"), {
                    "default": "qwen\\qwen_image_2.1_bf16.safetensors"}),
                "pose_clip_name": (folder_paths.get_filename_list("text_encoders"), {
                    "default": "qwen3vl_8b_bf16.safetensors"}),
                "pose_lora_name": (loras, {
                    "default": "qwen-image2.1\\VNCCS_QI2_PoseStudioV1.1.safetensors"}),
                "outfit_unet_name": (folder_paths.get_filename_list("diffusion_models"), {
                    "default": "qwen\\qwen_image_2.1_int8_convrot.safetensors"}),
                "outfit_clip_name": (folder_paths.get_filename_list("text_encoders"), {
                    "default": "qwen3vl_8b_int8_convrot.safetensors"}),
                "vae_name": (folder_paths.get_filename_list("vae"), {
                    "default": "qwen_image_2.1_vae_bf16.safetensors"}),
            },
            "optional": {
                "garment_description": ("STRING", {"forceInput": True}),
            },
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ("IMAGE", "IMAGE", "IMAGE")
    RETURN_NAMES = ("换头像结果", "换姿势结果", "换服饰结果")
    FUNCTION = "run"
    OUTPUT_NODE = True
    CATEGORY = "image/Pose Gallery/Qwen2.1"
    DESCRIPTION = "一个节点顺序完成换头像、换姿势、换服饰；节点内三个预览窗会按阶段立即刷新。"

    @classmethod
    def IS_CHANGED(cls, enable_face, enable_pose, enable_outfit, width, height,
                   steps, sampler_name, scheduler, seed, face_unet_name,
                   face_clip_name, pose_unet_name, pose_clip_name, pose_lora_name,
                   outfit_unet_name, outfit_clip_name, vae_name,
                   garment_description="", **kwargs):
        value = repr((
            enable_face, enable_pose, enable_outfit, width, height, steps,
            sampler_name, scheduler, seed, face_unet_name, face_clip_name,
            pose_unet_name, pose_clip_name, pose_lora_name, outfit_unet_name,
            outfit_clip_name, vae_name, garment_description,
        ))
        return hashlib.sha256(value.encode()).hexdigest()

    def run(self, person_image, portrait_image, pose_image, garment_image,
            enable_face, enable_pose, enable_outfit, width, height, steps,
            sampler_name, scheduler, seed, face_unet_name, face_clip_name,
            pose_unet_name, pose_clip_name, pose_lora_name, outfit_unet_name,
            outfit_clip_name, vae_name, garment_description="", unique_id=None):
        seed = int(seed) & 0xFFFFFFFF
        if sampler_name not in comfy.samplers.KSampler.SAMPLERS:
            sampler_name = "euler"
        if scheduler not in comfy.samplers.KSampler.SCHEDULERS:
            scheduler = "simple"
        steps = max(1, min(100, int(steps)))

        face_width, face_height = _resolve_output_size(person_image, 0, 0)
        face_image = person_image
        if enable_face:
            face_image = _run_qwen21_turbo_edit_stage(
                person_image, portrait_image, DEFAULT_FACE_PROMPT,
                face_unet_name, face_clip_name, vae_name,
                face_width, face_height, seed + 11,
            )
        _send_stage_preview(face_image, unique_id, "face")

        pose_width, pose_height = _resolve_output_size(face_image, 0, 0)
        pose_result = face_image
        if enable_pose:
            pose_result = _run_qwen21_pose_stage(
                face_image, pose_image, DEFAULT_PROMPT,
                pose_unet_name, pose_clip_name, vae_name, pose_lora_name,
                pose_width, pose_height, seed + 29, 25, "euler", "simple",
            )
        _send_stage_preview(pose_result, unique_id, "pose")

        outfit_width, outfit_height = _resolve_output_size(pose_result, width, height)
        outfit_image = pose_result
        if enable_outfit:
            description = (garment_description or "").strip()
            prompt = DEFAULT_SWAP_PROMPT
            if description:
                prompt += (
                    f" Exact outfit metadata from the garment reference: {description}. "
                    "Copy every named garment, legwear and footwear detail exactly."
                )
            outfit_image = _run_qwen21_edit_stage(
                pose_result, garment_image, prompt, outfit_unet_name,
                outfit_clip_name, vae_name, outfit_width, outfit_height,
                seed + 47, steps, sampler_name, scheduler, 2.5,
            )
        _send_stage_preview(outfit_image, unique_id, "outfit")

        return (face_image, pose_result, outfit_image)


# ---------------------------------------------------------------------------
# 节点 D：换装生成（Qwen-Image-Edit-2511，enable 开关，关闭时直通不换装）
# 复刻 nvzhuang 换装链路：人物图 image1（保身份保姿势）+ 服装图 image2（穿上）
# → TextEncodeQwenImageEditPlus → FluxKontextMultiReferenceLatentMethod
# → KSampler(4 步 Lightning, cfg=1.0) → VAEDecode
# ---------------------------------------------------------------------------
class PoseQwen21PoseSwap:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "person_image": ("IMAGE", {"tooltip": "换姿后的人物图（来自 PoseQwen21 姿态换姿生成输出）。换装时保持其身份、姿势与画风。"}),
                "garment_image": ("IMAGE", {"tooltip": "服装参考图（来自 PoseQwen21GarmentSelect 服装选择，或任意服装图）。"}),
                "enable": ("BOOLEAN", {"default": True,
                                       "tooltip": "换装开关：True 执行换装；False 节点不起作用，直接透传 person_image。"}),
                "prompt": ("STRING", {"default": DEFAULT_SWAP_PROMPT, "multiline": True,
                                      "tooltip": "换装提示词。默认无需修改。"}),
                "unet_name": (folder_paths.get_filename_list("diffusion_models"), {
                    "default": "qwen_image_edit_2511_int8_convrot.safetensors",
                    "tooltip": "Qwen-Image-Edit-2511 基础模型（建议 int8 版，16GB 显存可用）。请放入 diffusion_models/。"}),
                "clip_name": (folder_paths.get_filename_list("text_encoders"), {
                    "default": "qwen_2.5_vl_7b_fp8_scaled.safetensors",
                    "tooltip": "Qwen2.5-VL 7B 文本与图像编码器（type=qwen_image）。"}),
                "vae_name": (folder_paths.get_filename_list("vae"), {
                    "default": "qwen_image_vae.safetensors",
                    "tooltip": "Qwen Image Edit 配套 VAE。"}),
                "lora_name": (folder_paths.get_filename_list("loras"), {
                    "default": "Qwen-Edit-2511/Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors",
                    "tooltip": "2511 四步 Lightning LoRA。留空则按默认步数采样。"}),
                "lora_strength": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 2.0, "step": 0.05}),
                "shift": ("FLOAT", {"default": 3.1, "min": 0.0, "max": 100.0, "step": 0.01,
                                    "tooltip": "ModelSamplingAuraFlow shift（2511 换装推荐 3.1）。"}),
                "seed": ("INT", {"default": 20261029, "min": 0, "max": 4294967295, "control_after_generate": True}),
                "steps": ("INT", {"default": 4, "min": 1, "max": 10000}),
                "cfg": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 100.0, "step": 0.1, "round": 0.01}),
                "sampler_name": (comfy.samplers.KSampler.SAMPLERS, {"default": "euler"}),
                "scheduler": (comfy.samplers.KSampler.SCHEDULERS, {"default": "simple"}),
                "denoise": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01}),
            },
            "optional": {
                "garment_description": ("STRING", {
                    "default": "",
                    "forceInput": True,
                    "tooltip": "连接服装选择节点的 description 输出。会把具体款式、袜型和鞋型追加到换装提示词，显著改善鞋袜替换准确度。",
                }),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("image", "description")
    FUNCTION = "run"
    CATEGORY = "image/Pose Gallery/Qwen2.1"
    DESCRIPTION = "换装生成：person_image（换姿后人物）+ garment_image（服装）→ Qwen-Image-Edit-2511 换装 → 输出。enable=False 时直通 person_image（节点不起作用）。"

    @classmethod
    def IS_CHANGED(cls, person_image, garment_image, enable, seed, **kwargs):
        return hashlib.sha256(str(seed).encode()).hexdigest()

    @classmethod
    def VALIDATE_INPUTS(cls, **kwargs):
        return True

    def run(self, person_image, garment_image, enable, prompt, unet_name, clip_name,
            vae_name, lora_name, lora_strength, shift, seed, steps, cfg,
            sampler_name, scheduler, denoise, garment_description=None):
        # ---- 开关关闭：节点不起作用，直接透传人物图 ----
        if not enable:
            return (person_image, "")

        # ---- 参数容错 ----
        valid_samplers = set(comfy.samplers.KSampler.SAMPLERS)
        valid_schedulers = set(comfy.samplers.KSampler.SCHEDULERS)
        if sampler_name not in valid_samplers:
            sampler_name = "euler"
        if scheduler not in valid_schedulers:
            scheduler = "simple"
        try:
            steps = max(1, min(10000, int(steps)))
        except (TypeError, ValueError):
            steps = 4
        try:
            cfg = float(cfg)
        except (TypeError, ValueError):
            cfg = 1.0
        try:
            denoise = max(0.0, min(1.0, float(denoise)))
        except (TypeError, ValueError):
            denoise = 1.0
        try:
            seed = int(seed) & 0xFFFFFFFF
        except (TypeError, ValueError):
            seed = 0
        try:
            shift = float(shift)
        except (TypeError, ValueError):
            shift = 3.1
        try:
            lora_strength = float(lora_strength)
        except (TypeError, ValueError):
            lora_strength = 1.0

        # 1) 加载模型链：UNETLoader → ModelSamplingAuraFlow → CFGNorm → Lightning LoRA
        model = _cache_unet(unet_name)
        model = ModelSamplingAuraFlow().patch_aura(model, shift, sampling="flow")[0]
        model = CFGNorm.execute(model, 1.0, False).result[0]
        model = _apply_lora(model, lora_name, lora_strength)

        clip = _cache_clip(clip_name)
        vae = _cache_vae(vae_name)

        # 服装图库的文字描述含具体鞋型/袜型。Qwen Edit 对“鞋”这类泛称
        # 往往继续沿用人物原鞋；把款式名明确告诉模型后才能稳定替换。
        description = (garment_description or "").strip()
        if description:
            prompt = (
                f"{prompt.rstrip()}\n"
                f"Exact outfit metadata from the garment reference: {description}. "
                "Treat every named garment, legwear and footwear item as part of the "
                "complete outfit. Copy the exact footwear color, straps, platform, "
                "sole and heel visible in Picture 2; do not substitute a different "
                "shoe color."
            )

        # 2) 缩放人物图（FluxKontextImageScale）→ 人物 latent 作初始 latent
        person_scaled = FluxKontextImageScale.execute(person_image).result[0]
        latent = nodes.VAEEncode().encode(vae, person_scaled)[0]

        # 3) 编码：image1 = 缩放后人物图（保身份保姿势），image2 = 服装图（穿上）
        positive_out = TextEncodeQwenImageEditPlus.execute(
            clip, prompt, vae, person_scaled, garment_image,
        )
        positive = positive_out.result[0]
        positive = FluxKontextMultiReferenceLatentMethod.execute(
            positive, "index_timestep_zero",
        ).result[0]

        # negative：同构（人物图+服装图），空提示词
        negative_out = TextEncodeQwenImageEditPlus.execute(
            clip, "", vae, person_scaled, garment_image,
        )
        negative = negative_out.result[0]
        negative = FluxKontextMultiReferenceLatentMethod.execute(
            negative, "index_timestep_zero",
        ).result[0]

        # 4) 采样 + 解码
        latent = nodes.KSampler().sample(
            model, seed, steps, cfg, sampler_name, scheduler,
            positive, negative, latent, denoise,
        )[0]
        images = nodes.VAEDecode().decode(vae, latent)[0]

        return (images, "")


# ---------------------------------------------------------------------------
# 自带路由：姿势图库 + 服装图库全部由本插件服务，不依赖任何外部插件。
# ---------------------------------------------------------------------------
routes = PromptServer.instance.routes
print(f"[AICG3D-PoseSwap] PromptServer.instance present; routes table has {len(list(routes))} entries before adding")

# 幂等注册：插件可能被 AICG3D 工作台主动加载一次、ComfyUI 再加载一次，
# 同一路由只注册一次，避免 aiohttp 重复路径报错。
_route_paths = {getattr(r, "path", None) for r in routes}


def _register_route(path, handler, *, static=False):
    if static or path not in _route_paths:
        routes.get(path)(handler)
        _route_paths.add(path)


if "/aicg3d_pose/catalog" not in _route_paths:
    async def aicg3d_pose_catalog(request):
        try:
            return web.json_response(pose_data.records())
        except (ValueError, FileNotFoundError) as exc:
            return web.json_response({"error": str(exc)}, status=503)
    _register_route("/aicg3d_pose/catalog", aicg3d_pose_catalog)


if "/aicg3d_pose/assets/{kind}/{filename}" not in _route_paths:
    async def aicg3d_pose_assets(request):
        try:
            path = pose_data.asset(request.match_info["kind"], request.match_info["filename"])
            return web.FileResponse(path, headers={"Cache-Control": "private, max-age=3600"})
        except (ValueError, FileNotFoundError):
            raise web.HTTPNotFound()
    _register_route("/aicg3d_pose/assets/{kind}/{filename}", aicg3d_pose_assets)


if "/aicg3d_pose/gallery" not in _route_paths:
    async def aicg3d_pose_gallery(request):
        return web.FileResponse(
            pose_data.ROOT / "web" / "gallery.html",
            headers={"Cache-Control": "no-cache"},
        )
    _register_route("/aicg3d_pose/gallery", aicg3d_pose_gallery)


if "/aicg3d_pose/garments/catalog" not in _route_paths:
    async def aicg3d_pose_garments_catalog(request):
        try:
            return web.json_response(garment_data.records())
        except (ValueError, FileNotFoundError) as exc:
            return web.json_response({"error": str(exc)}, status=503)
    _register_route("/aicg3d_pose/garments/catalog", aicg3d_pose_garments_catalog)


if "/aicg3d_pose/garments/assets/{filename}" not in _route_paths:
    async def aicg3d_pose_garments_assets(request):
        try:
            path = garment_data.asset(request.match_info["filename"])
            return web.FileResponse(path, headers={"Cache-Control": "private, max-age=3600"})
        except (ValueError, FileNotFoundError):
            raise web.HTTPNotFound()
    _register_route("/aicg3d_pose/garments/assets/{filename}", aicg3d_pose_garments_assets)


if "/aicg3d_pose/garments/gallery" not in _route_paths:
    async def aicg3d_pose_garments_gallery(request):
        return web.FileResponse(
            garment_data.ROOT / "web" / "garment_gallery.html",
            headers={"Cache-Control": "no-cache"},
        )
    _register_route("/aicg3d_pose/garments/gallery", aicg3d_pose_garments_gallery)


if "/aicg3d_pose/portraits/catalog" not in _route_paths:
    async def aicg3d_pose_portraits_catalog(request):
        try:
            return web.json_response(
                {"records": portrait_data.records(), "meta": portrait_data.metadata()},
                headers={"Cache-Control": "no-store"},
            )
        except (ValueError, FileNotFoundError) as exc:
            return web.json_response({"error": str(exc)}, status=503)
    _register_route("/aicg3d_pose/portraits/catalog", aicg3d_pose_portraits_catalog)


if "/aicg3d_pose/portraits/thumb/{filename}" not in _route_paths:
    async def aicg3d_pose_portraits_thumb(request):
        filename = request.match_info["filename"]
        if Path(filename).name != filename or Path(filename).suffix.lower() != ".webp":
            raise web.HTTPNotFound()
        try:
            path = await asyncio.to_thread(portrait_data.ensure_thumb, Path(filename).stem)
            return web.FileResponse(path, headers={"Cache-Control": "private, max-age=86400"})
        except (ValueError, FileNotFoundError, OSError):
            raise web.HTTPNotFound()
    _register_route("/aicg3d_pose/portraits/thumb/{filename}", aicg3d_pose_portraits_thumb)


if "/aicg3d_pose/portraits/gallery" not in _route_paths:
    async def aicg3d_pose_portraits_gallery(request):
        return web.FileResponse(
            pose_data.ROOT / "web" / "portrait_gallery.html",
            headers={"Cache-Control": "no-cache"},
        )
    _register_route("/aicg3d_pose/portraits/gallery", aicg3d_pose_portraits_gallery)


NODE_CLASS_MAPPINGS = {
    "PoseQwen21PoseSelect": PoseQwen21PoseSelect,
    "PoseQwen21GarmentSelect": PoseQwen21GarmentSelect,
    "PoseQwen21PortraitSelect": PoseQwen21PortraitSelect,
    "PoseQwen21": PoseQwen21,
    "PoseQwen21FaceStage": PoseQwen21FaceStage,
    "PoseQwen21PoseStage": PoseQwen21PoseStage,
    "PoseQwen21OutfitStage": PoseQwen21OutfitStage,
    "PoseQwen21PoseSwap": PoseQwen21PoseSwap,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "PoseQwen21PoseSelect": "AICG3D PoseSwap → 姿势姿态控制",
    "PoseQwen21GarmentSelect": "AICG3D PoseSwap → 服装选择",
    "PoseQwen21PortraitSelect": "AICG3D PoseSwap → 换头换脸参考选择",
    "PoseQwen21": "AICG3D PoseSwap → Qwen2.1 姿态换姿生成",
    "PoseQwen21FaceStage": "内部：换头像",
    "PoseQwen21PoseStage": "内部：换姿势",
    "PoseQwen21OutfitStage": "内部：换服饰",
    "PoseQwen21PoseSwap": "AICG3D PoseSwap → Qwen Edit 2511 换装生成",
}
WEB_DIRECTORY = "./web"
__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 JGRFW
