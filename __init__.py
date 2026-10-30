"""comfyui-aicg3d-PoseSwap: 完全独立的「选姿势/选服装 → Qwen 换姿/换装」插件。

零外部插件依赖：
- 姿势图库（library/）与服装图库（garments/）均随插件目录分发
- 姿势图库 / 服装图库浏览页面（web/gallery.html / web/garment_gallery.html）
  与 /aicg3d_pose/* 路由由本插件自带
- 换姿节点只需 ComfyUI 原生 Qwen Image 2.1 节点（ComfyUI 0.43+）与 models/ 权重
- 换装节点只需 ComfyUI 原生 Qwen-Image-Edit-2511 节点（TextEncodeQwenImageEditPlus /
  FluxKontext* / ModelSamplingAuraFlow / CFGNorm）与 models/ 权重

一条线连接：
  [PoseQwen21PoseSelect 姿势姿态控制] --pose_image--> [PoseQwen21 姿态换姿生成]
  [PoseQwen21GarmentSelect 服装选择]   --garment_image--> [PoseQwen21PoseSwap 换装生成（enable 开关）]
"""
import hashlib

import folder_paths
import nodes
import comfy.samplers
from aiohttp import web
from server import PromptServer
from comfy_extras.nodes_qwen import TextEncodeQwenImage21, QwenImage21Cache, TextEncodeQwenImageEditPlus
from comfy_extras.nodes_flux import FluxKontextImageScale, FluxKontextMultiReferenceLatentMethod
from comfy_extras.nodes_cfg import CFGNorm
from comfy_extras.nodes_model_advanced import ModelSamplingAuraFlow

from . import pose_data
from . import garment_data

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
    "shown in image1 as faithfully as possible. image1 is the only source for the "
    "pose, skeletal structure and body proportions of the figure; copy it precisely. "
    "image2 is the only source for the person's identity: keep the EXACT same person, "
    "same face, same hairstyle, same clothing with all colors, fabric, patterns, "
    "accessories and shoes unchanged, same background and same lighting as in image2. "
    "Do NOT alter, replace, remove, recolor or redraw the outfit from image2; do not "
    "change the person or their style. Do not copy the line drawing, mannequin shape, "
    "or any annotations from image1."
)

# 换装提示词：参考 nvzhuang 换装链路的 enPrompt 核心要求（保身份/保姿势/穿上服装图）
DEFAULT_SWAP_PROMPT = (
    "You are a professional fashion virtual try-on assistant. Dress the person in "
    "image1 wearing the exact garment shown in image2, and output a single "
    "photorealistic full-body or half-body photo. Strict requirements: "
    "1. Keep the person's identity EXACTLY the same: same face, facial features, "
    "skin tone, hairstyle, body type and proportions. Do not change who they are. "
    "2. Keep the person's original pose, body angle and orientation as much as "
    "possible; only adjust arms/limbs if strictly needed to fit the garment naturally. "
    "3. Put the exact garment from image2 onto the person: preserve its color, fabric "
    "texture, pattern, neckline, sleeve length, hem length and silhouette faithfully. "
    "Do not redesign or simplify the garment. "
    "4. The garment must drape naturally on the body and cast realistic folds, "
    "shadows and highlights consistent with the original lighting. "
    "5. Keep the original background, lighting and overall mood of the person's photo. "
    "6. Photorealistic, high detail, professional fashion editorial quality, 8k, "
    "natural skin texture. Output ONLY the final dressed-up photograph, nothing else."
)


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
            sampler_name, scheduler, denoise):
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


NODE_CLASS_MAPPINGS = {
    "PoseQwen21PoseSelect": PoseQwen21PoseSelect,
    "PoseQwen21GarmentSelect": PoseQwen21GarmentSelect,
    "PoseQwen21": PoseQwen21,
    "PoseQwen21PoseSwap": PoseQwen21PoseSwap,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "PoseQwen21PoseSelect": "AICG3D PoseSwap → 姿势姿态控制",
    "PoseQwen21GarmentSelect": "AICG3D PoseSwap → 服装选择",
    "PoseQwen21": "AICG3D PoseSwap → Qwen2.1 姿态换姿生成",
    "PoseQwen21PoseSwap": "AICG3D PoseSwap → Qwen Edit 2511 换装生成",
}
WEB_DIRECTORY = "./web"
__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
