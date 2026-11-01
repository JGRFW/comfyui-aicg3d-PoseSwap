<img width="1615" height="486" alt="image" src="https://github.com/user-attachments/assets/0f35cd8d-efb8-4540-a2bc-e4022fbdc3c6" />

# comfyui-aicg3d-PoseSwap

项目作者/维护者：JGRFW。项目源代码采用 MIT License，版权声明见 [LICENSE](LICENSE)，上游作者与素材来源见 [AUTHORS.md](AUTHORS.md)。

> [!IMPORTANT]
> MIT 只覆盖项目源代码。`library/`、`garments/`、`portraits/` 中的图片和索引属于第三方素材，不在 MIT 范围内；模型权重也不随仓库提供。
> 当前姿势图库明确限制商业使用，服装图库未找到覆盖再分发的许可证，人像图库虽标注 CC0 但同时请求避免再分发。公开发布完整素材包前必须阅读 [LEGAL_AND_SAFETY.md](LEGAL_AND_SAFETY.md)、[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 和 [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md)。免责声明不能替代授权。
>
> 内容提示：姿势与服装索引包含成人向分类。项目仅面向成年人；不得用于未成年人性化、非自愿性化、冒充真实人物或其他违法用途。


完全独立的 ComfyUI 插件：**换头换发 → Qwen Image 2.1 换姿势 → 换全套服装**，也可以使用 Qwen-Image-Edit-2511 做单次高保真换装。

推荐使用“双封装”工作流：素材输入四合一子图 + 一键替换子图，三个替换结果分别从三个输出端连接标准 PreviewImage。

「我生成一个人物，选一个姿势，出来就是我的这个人物摆出所选姿势；再选一套服装，还能让他/她当场换装。」

## 图库来源与分发状态

当前完整开发目录可以同时保留三套本地图库；推荐的公开代码-only 包只包含读取和浏览逻辑，不包含图片，避免把未授权素材随源码公开。两种模式都支持环境变量指向外部图库目录：

素材来源、许可与责任说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 和 [PORTRAIT_LIBRARY_NOTICE.md](PORTRAIT_LIBRARY_NOTICE.md)。

| 依赖来源 | 说明 |
| --- | --- |
| **姿势图库** | **当前开发目录自带**（`library/`，1439 张原图 + 1439 张缩略图 + 中文索引）；公开代码-only 包默认排除 |
| **服装图库** | **当前开发目录自带**（`garments/`，1407 张服装参考图 + 索引）；公开代码-only 包默认排除 |
| **人像图库** | **当前开发目录自带压缩版**（`portraits/`，1499 张 WebP + 缩略图 + 索引）；公开代码-only 包默认排除 |
| **图库浏览页面与路由** | 由本插件自带（`web/gallery.html`、`web/garment_gallery.html` + `/aicg3d_pose/*` 全部路由），不调用任何外部插件 |
| **ComfyUI** | 0.43+（含原生 Qwen Image 2.1 与 Qwen-Image-Edit-2511 节点：`nodes_qwen.py` / `nodes_flux.py` / `nodes_cfg.py` / `nodes_model_advanced.py`） |
| **模型权重** | 标准 `models/` 目录（见下表），ComfyUI 通用存放位置，不属于任何插件 |

> 别人使用时只需：① 拷贝本插件整个目录到其 ComfyUI 的 `custom_nodes/`；
> ② 按下方「依赖模型」准备好权重文件；③ 重启 ComfyUI。当前完整开发目录包含本地图库，但推荐的公开代码-only 包不包含第三方图库，使用者需通过三个 `AICG3D_*_LIBRARY` 环境变量指向自行合法取得的素材目录。

## 安装

本项目自身不需要额外执行 `pip install`；图像读取使用 ComfyUI 已带的 Pillow、NumPy 和 PyTorch。

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/JGRFW/comfyui-aicg3d-PoseSwap.git
```

然后按 [MODEL_REQUIREMENTS.md](MODEL_REQUIREMENTS.md) 下载不随仓库提供的模型权重，重启 ComfyUI。
代码-only 发布包可使用 `python scripts/package_open_source.py` 生成；它默认排除第三方图库。

## 六个节点（含双子图封装工作流）

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
 · description ─────────────────────────►   · garment_description（鞋袜/款式描述）
                                              · enable 开关：关闭时节点不起作用，直接透传
                                              · 模型/采样参数
                                              · 输出换装成图 image
```

换装节点 `enable` 为 **False** 时节点不起作用：直接原样透传 `person_image`，不加载换装模型、不做任何生成。需要换衣时置 **True** 即可。

`description` 那条线不要省略：图库描述里的具体鞋型、袜型会追加到换装提示词。
Qwen Edit 对泛称“鞋”很容易继续沿用原鞋；明确告诉它 `socks sandals` 等词后才能稳定替换。

## 三种使用方式

| 路线 | 适用场景 | 模型体积 | 工作流 |
| --- | --- | --- | --- |
| **双封装顺序替换（推荐）** | 素材输入四合一 + 一键替换子图；三个替换结果分别从三个输出端顺序预览 | 头像/姿势共享一套模型，换服饰另用一套 | `example_workflows/aicg3d_qwen21_simple_replace.json` |
| **Qwen Image 2.1 三段预览** | 16GB 显存，换头换发、换姿势、换全套服装一次跑完；每一步都能预览 | int8 主模型约 6.76 GiB | `example_workflows/aicg3d_qwen21_three_stage.json` |
| **Qwen-Image-Edit-2511 节点** | 单次换装，追求更直接的服装图保真；适合已准备量化 2511 权重 | int8 量化体积明显低于 bf16；bf16 约 38 GiB | 插件内 `PoseQwen21PoseSwap` 节点或 `aicg3d_poseswap_pose_swap_edit.json` |

## 双封装顺序替换工作流

把 [example_workflows/aicg3d_qwen21_simple_replace.json](example_workflows/aicg3d_qwen21_simple_replace.json) 拖进 ComfyUI。工作流按以下顺序串联：

画布上有两个封装节点和三个标准预览节点：

```text
素材输入 · 四合一 → 一键替换 · 头像 → 姿势 → 服饰
一键替换输出 1 → 预览 1 · 换头像
一键替换输出 2 → 预览 2 · 换姿势
一键替换输出 3 → 预览 3 · 换服饰
```

一键替换子图内有三个开关：

- `换头像开关`：关闭时直接把底图传给换姿势阶段。
- `换姿势开关`：关闭时直接把换头像结果传给换服饰阶段。
- `换服饰开关`：关闭时直接输出换姿势结果。

三个预览全部连接子图输出端口。子图内部仍然按顺序执行三个阶段，因此预览 1、2、3 会依次刷新，不会等全部完成后才一起出现。

模型配置已合并：换头像和换姿势共享同一套主模型、编码器、LoRA 与 VAE；换服饰单独使用一套主模型和编码器，不再重复加载同一个模型。

一键替换子图常用参数：

- `自定义宽度 / 高度`：默认都是 `0`，表示保持输入图原始比例；长边自动限制为 1344，避免无意义放大。填写具体宽度或高度后可覆盖。
- `换服饰步数`：默认 `20`；服装细节仍不稳定时可提高到 `25–30`。
- `采样器 / 调度器`：只作用于换服饰阶段；默认 `euler / simple`。

三段工作流把“换脸/换发型”和“换装”拆开，避免一次改太多属性导致脸部、发型和服装互相干扰。多参考图合并成一次 Qwen 2.1 编辑也能运行，但稳定性和可回退性不如分段。

## 三段工作流怎么用

1. 把 [example_workflows/aicg3d_qwen21_three_stage.json](example_workflows/aicg3d_qwen21_three_stage.json) 拖进 ComfyUI。
2. `1. 人物底图` 选要保留身体和姿势的底图；`2. 换头参考` 选脸；`3. 换发型参考` 选头发。
3. `4. 换姿势参考` 从姿势图库选动作，`5. 换全套服装参考` 从服装图库选套装。
4. 点击运行。工作流会依次输出并保存 `1_head_hair`、`2_pose`、`3_outfit` 三张图。
5. 不需要换头或换发型时，把对应参考图替换成同一张底图，或直接把该段输出接到下一段；不需要换装时，把 `3. 换全套服装后` 保存节点停用。

三段里的 Qwen 2.1 编辑节点默认 `refine_prompt = false`，直接使用写好的中文提示词。打开后才会调用提示词增强器，速度会额外增加。

## 人像参考节点：换头换脸参考选择

`PoseQwen21PortraitSelect` 用于从人像图库选择正脸或造型参考，输出 `portrait_image`、`portrait_id`、`description` 和 `attribution`。将 `portrait_image` 接到换脸/换头链路的身份参考输入即可；节点本身不自动运行。

- 图库来源：[AI モデル顔データベース](https://ai-portrait-gallery.pages.dev/)，原作者 [あぎ（@agi_aibusi）](https://x.com/agi_aibusi)。
- 原站标注 CC0 1.0，同时请求避免直接再分发图片数据本身；本插件按开源分发需求包含压缩副本，并在 `PORTRAIT_LIBRARY_NOTICE.md` 中保留该请求和自行合规提示。
- 素材随插件存放在 `portraits/`：1499 张最大 768×960 WebP 参考图与 360×450 WebP 缩略图，约 148 MiB。
- 人像节点读取插件内 `portraits/`，不依赖 `E:` 盘、外部图库插件或 ComfyUI `user` 缓存。
- 每个卡片和详情页都保留原站、原作者、CC0 许可链接；完整声明见 `PORTRAIT_LIBRARY_NOTICE.md`。
- 该节点是独立的非官方本地索引工具，不代表原作者官方版本或背书。不得用于冒充真实人物或违法违规用途。

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
  - 默认提示词：精确复制姿势 + 锁死服装不变 + 保持原图赤脚/袜装状态。
    提示词会明确说明“原图赤脚则保持赤脚”“只有袜/裤袜则不要加鞋”，防止换姿时凭空生成鞋子。

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
  - 新版换装提示词会完整替换上衣、下装、袜/裤袜与鞋；如果参考图有不同鞋型，
    旧鞋必须移除后替换，不能保留或混合。
  - `garment_description` 接入服装图库描述（例如 `socks sandals`），弥补小尺寸鞋部在视觉编码中不醒目的问题。

## 使用

1. 拖入节点（菜单 **image → Pose Gallery/Qwen2.1**，或已集成 AICG3D 工作台时在 **AICG3D/图像与姿势**）。
2. **换姿**：「姿态换姿生成」的 `person_image` 接人物参考图（成人参考图），
   「姿势姿态控制」的 `pose_image` 连到其 `pose_image` 输入（一条线）。
3. 在姿势姿态控制节点点击「**浏览姿势图库**」，搜索/分类/多视角筛选，点「使用此姿势」。
4. **换装（可选）**：「换装生成」的 `person_image` 接上一步换姿成图，
   「服装选择」的 `garment_image` 连到其 `garment_image` 输入（一条线）。
   再把「服装选择」的 `description` 连到「换装生成」的 `garment_description`。
5. 在服装选择节点点击「**浏览服装图库**」，按分类/关键词筛选，点「使用此服装」。
6. 需要换衣时把「换装生成」的 `enable` 置 **True**；不需要则置 **False**（节点直通，不生效）。
7. 保持模型默认路径，点击运行。

## 依赖模型（models/ 目录下）

### 换姿（Qwen Image 2.1）

| 类型 | 默认文件 | 说明/来源 |
| --- | --- | --- |
| 基础模型 | `diffusion_models/qwen/qwen_image_2.1_bf16.safetensors` | Qwen-Image-2.1（通义千问官方） |
| 文本/图像编码器 | `text_encoders/qwen3vl_8b_int8_convrot.safetensors` | 推荐工作流默认；如节点下拉使用 bf16 版也可切换 |
| VAE | `vae/qwen_image_2.1_vae_bf16.safetensors` | Qwen Image 2.1 配套 VAE |
| 姿态适配器 LoRA | `loras/qwen-image2.1/VNCCS_QI2_PoseStudioV1.1.safetensors` | HuggingFace `MIUProject/VNCCS_PoseStudio_QI2.1` |

默认采样：25 步、CFG 1、Euler/simple、denoise 1、LoRA 强度 1、resolution 1024。

### 换头换发 + 换装（Qwen Image 2.1 三段工作流）

| 类型 | 默认文件 | 说明 |
| --- | --- | --- |
| 基础模型 | `diffusion_models/qwen/qwen_image_2.1_int8_convrot.safetensors` | **16GB 显存推荐**；可切换 bf16 |
| 文本/图像编码器 | `text_encoders/qwen3vl_8b_int8_convrot.safetensors` | Qwen3-VL 8B int8（type=qwen_image） |
| VAE | `vae/qwen_image_2.1_vae_bf16.safetensors` | 与换姿共用 |
| 换头像模型 | `diffusion_models/qwen/qwen_image_2.1_int8_convrot.safetensors` | 8 步快速换头像 |
| 换服饰模型 | `diffusion_models/qwen/qwen_image_2.1_int8_convrot.safetensors` | 默认 20 步，可调整采样器、调度器和步数 |

推荐的双封装工作流实际配置为：换头像与换姿势共享 `qwen_image_2.1_bf16`、`qwen3vl_8b_int8_convrot` 和同一 VAE；姿势阶段再应用姿势 LoRA；换服饰使用独立的 `qwen_image_2.1_int8_convrot` 和同一套 CLIP/VAE。换头像采用 8 步 sigma 计划，换姿势默认 25 步，换服饰默认 20 步。

### 换装（Qwen-Image-Edit-2511）

| 类型 | 默认文件 | 说明/来源 |
| --- | --- | --- |
| 基础模型 | `diffusion_models/qwen_image_edit_2511_int8_convrot.safetensors` | **int8 版，16GB 显存可跑；需自行下载**（Comfy-Org / Qwen 官方 2511 仓库的 ComfyUI 单文件版） |
| 文本/图像编码器 | `text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors` | Qwen2.5-VL 7B fp8（type=qwen_image） |
| VAE | `vae/qwen_image_vae.safetensors` | Qwen Image Edit 配套 VAE |
| Lightning LoRA | `loras/Qwen-Edit-2511/Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors` | 4 步极速（也可用 fp32 版） |

默认采样：4 步、CFG 1、Euler/simple、denoise 1、LoRA 强度 1、shift 3.1。
所有模型名均为下拉可选；若你的模型文件名不同，在下拉中选择即可。

> **16GB 显存务必使用量化版 2511**：bf16 基础模型约 38GB，会大量从磁盘换入显存，
> 单次换装常见 110 秒以上；int8/fp8 量化版权重大幅下降，通常能显著缩短耗时。
> 不要为了“更精细”把 Lightning 4 步改成 25 步；4 步 LoRA 配 25 步只会慢约 6 倍，
> 不会带来成比例的质量提升。
>
> 在 RTX 5070 Ti 16GB 上实测，Qwen 2.1 三段完整链路（换头换发 → 25 步换姿势 → 8 步换全套服装）约 80 秒；
> 同一套 2511 bf16 链路仅换装常需 110 秒以上。Qwen 2.1 的优势主要是显存占用低、可多参考图；
> 如果服装细节仍不够准确，再用已量化的 2511 单独补一次换装。

> **换姿 LoRA 版本**：V1.1 保服装、姿势跟随适中（默认）；V2 姿势跟随更强但会改服装。
> 需要 V2 时下载 `VNCCS_QI2_PoseStudioV2.safetensors`（注意 HF 该文件名末尾带空格，
> 用 `%20` 编码直链下载，保存时去掉空格）到 `loras/qwen-image2.1/` 后在下拉选择。

## 环境变量（可选）

- `AICG3D_POSE_LIBRARY`：自定义姿势图库根目录（默认使用插件自带 `library/`）。
- `AICG3D_GARMENT_LIBRARY`：自定义服装图库根目录（默认使用插件自带 `garments/`）。
- `AICG3D_PORTRAIT_LIBRARY`：覆盖默认插件内 `portraits/`，可指向兼容的人像图库目录。
- `AICG3D_PORTRAIT_CACHE`：自定义人像压缩预览缓存目录（默认 `ComfyUI/user/aicg3d_portrait_cache/`）。

## 可选：集成进 AICG3D 短剧工作台

插件已适配 `comfyui-AICG3D`：其 registry 惰性导入本插件，重启后 AICG3D 菜单出现
**AICG3D/图像与姿势 → AICG3D PoseSwap → 姿势姿态控制 / 服装选择 / 换头换脸参考选择 / 一键替换 / 姿态换姿生成 / 换装生成**。
独立插件缺失时 AICG3D 照常加载，不影响工作台。

## 验证

- `py_compile` 通过；`node --check web/pose_qwen21.js`、`node --check web/garment_qwen21.js` 通过。
- `node --check web/portrait_qwen21.js` 通过；人像图库与节点输出已完成本地接口验证。
- `node --check web/pipeline_qwen21.js` 通过；素材输入四合一子图、一键替换子图和三个标准输出预览均已在 ComfyUI 前端实际加载验证。
- 路由自服务：`/aicg3d_pose/catalog`、`/aicg3d_pose/assets/`、`/aicg3d_pose/gallery`、
  `/aicg3d_pose/garments/catalog`、`/aicg3d_pose/garments/assets/`、`/aicg3d_pose/garments/gallery`。
- 人像路由：`/aicg3d_pose/portraits/catalog`、`/aicg3d_pose/portraits/thumb/`、`/aicg3d_pose/portraits/gallery`。
- 图库从插件 `library/` 加载姿势、`garments/` 加载服装均为本插件自带。
- 人像从插件 `portraits/` 加载，不依赖外部图库或 `E:` 盘。
- Qwen 2.1 多参考图、单换装、单换脸和三段完整链路均已在 ComfyUI API 中运行成功。
- 顺序预览事件已验证按 `换头像 → 换姿势 → 换服饰` 到达。
- 双子图完整链路运行成功，约 `90.5 秒`；三个输出端依次产生 `768 × 1344` 预览，自定义 `640 × 960` 测试输出也精确匹配。
- 模型下拉已收回子图内部真实加载节点，主封装节点不再出现误报的“未知模型/缺失模型”。
- 完整生成需 ComfyUI 运行时 + GPU + 上述模型，安装后重启验证。
