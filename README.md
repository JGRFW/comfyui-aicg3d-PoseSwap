# comfyui-aicg3d-PoseSwap

完全独立的 ComfyUI 插件：**选姿势 → Qwen Image 2.1 姿态换姿 →（可选）选服装 → Qwen-Image-Edit-2511 换装**。

「我生成一个人物，选一个姿势，出来就是我的这个人物摆出所选姿势；再选一套服装，还能让他/她当场换装。」

## 完全独立，可分享

本插件**零外部插件依赖**，拷给任何人、任何电脑，放进 `custom_nodes/` 就能一模一样地用：

| 依赖来源 | 说明 |
| --- | --- |
| **姿势图库** | **随插件自带**（`library/`，1439 张原图 + 1439 张缩略图 + 中文索引），不依赖 comfyui-pose-gallery |
| **服装图库** | **随插件自带**（`garments/`，1407 张服装参考图 + 索引），不依赖 nvzhuang 或其他外部项目 |
| **图库浏览页面与路由** | 由本插件自带（`web/gallery.html`、`web/garment_gallery.html` + `/aicg3d_pose/*` 全部路由），不调用任何外部插件 |
| **ComfyUI** | 0.43+（含原生 Qwen Image 2.1 与 Qwen-Image-Edit-2511 节点：`nodes_qwen.py` / `nodes_flux.py` / `nodes_cfg.py` / `nodes_model_advanced.py`） |
| **模型权重** | 标准 `models/` 目录（见下表），ComfyUI 通用存放位置，不属于任何插件 |

> 别人使用时只需：① 拷贝本插件整个目录到其 ComfyUI 的 `custom_nodes/`；
> ② 按下方「依赖模型」准备好权重文件；③ 重启 ComfyUI。图库无需任何额外下载。

## 四个节点（两条线连接）

```
                        pose_image（一条线）
[姿势姿态控制] ────────────────────────────►  [姿态换姿生成]
 PoseQwen21PoseSelect                         PoseQwen21
 · pose_id + 浏览姿势图库按钮 + 姿势预览      · person_image（人物参考图）
 · 输出 pose_image / pose_id / description   · pose_image（来自左侧节点）
                                              · 模型/采样参数
                                              · 输出换姿成图 image
                                                   │
                                                   │ image（换姿后人物）
                                                   ▼
                         garment_image（一条线）
[服装选择] ────────────────────────────────►  [换装生成]
 PoseQwen21GarmentSelect                      PoseQwen21PoseSwap
 · garment_id + 浏览服装图库按钮 + 预览      · person_image（换姿后人物）
 · 输出 garment_image / id / description     · garment_image（来自左侧节点）
                                              · enable 开关：关闭时节点不起作用，直接透传
                                              · 模型/采样参数
                                              · 输出换装成图 image
```

换装节点 `enable` 为 **False** 时节点不起作用：直接原样透传 `person_image`，不加载换装模型、不做任何生成。需要换衣时置 **True** 即可。

## 原理

- **换姿引擎**：千问 image 2.1（Qwen Image 2.1）。生成节点内部复现 ComfyUI 原生 Qwen 2.1
  姿态编辑链路：

  ```
  人物参考图(image_2) ─┐
  姿势原图(image_1) ───┤→ TextEncodeQwenImage21 → LoRA(姿态适配器) → Cache → KSampler → VAEDecode → IMAGE
                       │
          (姿势原图来自插件自带的 library/ 图库)
  ```

  - `image_1` = 姿势姿态控制节点输出的图库姿势原图（决定动作/姿态/视角）
  - `image_2` = 你生成/加载的人物参考图（保留身份、发型、服装、画风、背景、光照）
  - 默认提示词：精确复制姿势 + 锁死服装不变

- **换装引擎**：Qwen-Image-Edit-2511（4 步 Lightning 极速换装，复刻 nvzhuang 换装链路的官方参数）：

  ```
  人物图(换姿后) ──FluxKontextImageScale──► VAEEncode（初始 latent）
  服装图 ───────────────┐
  → TextEncodeQwenImageEditPlus(image1=人物图, image2=服装图, prompt=换装提示词)
  → FluxKontextMultiReferenceLatentMethod(index_timestep_zero)
  → ModelSamplingAuraFlow(shift=3.1) + CFGNorm(1.0) + Lightning LoRA
  → KSampler(4 步, cfg=1.0, euler/simple) → VAEDecode → IMAGE
  ```

  - 换装提示词：保持人物身份完全一致（脸/肤色/发型/体型）、尽量保持原姿势、
    忠实穿上服装图（颜色/面料/图案/领口/袖长/下摆不重设计）、自然垂坠、保留背景光照。

## 使用

1. 拖入节点（菜单 **image → Pose Gallery/Qwen2.1**，或已集成 AICG3D 工作台时在 **AICG3D/图像与姿势**）。
2. **换姿**：「姿态换姿生成」的 `person_image` 接人物参考图（成人参考图），
   「姿势姿态控制」的 `pose_image` 连到其 `pose_image` 输入（一条线）。
3. 在姿势姿态控制节点点击「**浏览姿势图库**」，搜索/分类/多视角筛选，点「使用此姿势」。
4. **换装（可选）**：「换装生成」的 `person_image` 接上一步换姿成图，
   「服装选择」的 `garment_image` 连到其 `garment_image` 输入（一条线）。
5. 在服装选择节点点击「**浏览服装图库**」，按分类/关键词筛选，点「使用此服装」。
6. 需要换衣时把「换装生成」的 `enable` 置 **True**；不需要则置 **False**（节点直通，不生效）。
7. 保持模型默认路径，点击运行。

## 依赖模型（models/ 目录下）

### 换姿（Qwen Image 2.1）

| 类型 | 默认文件 | 说明/来源 |
| --- | --- | --- |
| 基础模型 | `diffusion_models/qwen/qwen_image_2.1_bf16.safetensors` | Qwen-Image-2.1（通义千问官方） |
| 文本/图像编码器 | `text_encoders/qwen3vl_8b_bf16.safetensors` | Qwen3-VL 8B（type=qwen_image） |
| VAE | `vae/qwen_image_2.1_vae_bf16.safetensors` | Qwen Image 2.1 配套 VAE |
| 姿态适配器 LoRA | `loras/qwen-image2.1/VNCCS_QI2_PoseStudioV1.1.safetensors` | HuggingFace `MIUProject/VNCCS_PoseStudio_QI2.1` |

默认采样：25 步、CFG 1、Euler/simple、denoise 1、LoRA 强度 1、resolution 1024。

### 换装（Qwen-Image-Edit-2511）

| 类型 | 默认文件 | 说明/来源 |
| --- | --- | --- |
| 基础模型 | `diffusion_models/qwen_image_edit_2511_int8_convrot.safetensors` | **int8 版，16GB 显存可跑；需自行下载**（Comfy-Org / Qwen 官方 2511 仓库的 ComfyUI 单文件版） |
| 文本/图像编码器 | `text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors` | Qwen2.5-VL 7B fp8（type=qwen_image） |
| VAE | `vae/qwen_image_vae.safetensors` | Qwen Image Edit 配套 VAE |
| Lightning LoRA | `loras/Qwen-Edit-2511/Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors` | 4 步极速（也可用 fp32 版） |

默认采样：4 步、CFG 1、Euler/simple、denoise 1、LoRA 强度 1、shift 3.1。
所有模型名均为下拉可选；若你的模型文件名不同，在下拉中选择即可。

> **换姿 LoRA 版本**：V1.1 保服装、姿势跟随适中（默认）；V2 姿势跟随更强但会改服装。
> 需要 V2 时下载 `VNCCS_QI2_PoseStudioV2.safetensors`（注意 HF 该文件名末尾带空格，
> 用 `%20` 编码直链下载，保存时去掉空格）到 `loras/qwen-image2.1/` 后在下拉选择。

## 环境变量（可选）

- `AICG3D_POSE_LIBRARY`：自定义姿势图库根目录（默认使用插件自带 `library/`）。
- `AICG3D_GARMENT_LIBRARY`：自定义服装图库根目录（默认使用插件自带 `garments/`）。

## 可选：集成进 AICG3D 短剧工作台

插件已适配 `comfyui-AICG3D`：其 registry 惰性导入本插件，重启后 AICG3D 菜单出现
**AICG3D/图像与姿势 → AICG3D PoseSwap → 姿势姿态控制 / 服装选择 / 姿态换姿生成 / 换装生成**。
独立插件缺失时 AICG3D 照常加载，不影响工作台。

## 验证

- `py_compile` 通过；`node --check web/pose_qwen21.js`、`node --check web/garment_qwen21.js` 通过。
- 路由自服务：`/aicg3d_pose/catalog`、`/aicg3d_pose/assets/`、`/aicg3d_pose/gallery`、
  `/aicg3d_pose/garments/catalog`、`/aicg3d_pose/garments/assets/`、`/aicg3d_pose/garments/gallery`。
- 图库从插件 `library/` 加载姿势、`garments/` 加载服装均为本插件自带。
- 完整生成需 ComfyUI 运行时 + GPU + 上述模型，安装后重启验证。
