# 模型依赖与许可说明

本项目不包含模型权重。ComfyUI 和模型作者对权重、派生模型及 LoRA 分别适用自己的许可证；下载、商用、托管、再分发和输出用途必须以下载页面的最新条款为准。

## 推荐工作流所需文件

| 目录 | 默认文件 | 用途 |
| --- | --- | --- |
| `models/diffusion_models/qwen/` | `qwen_image_2.1_bf16.safetensors` | 换头像、换姿势共享主模型 |
| `models/diffusion_models/qwen/` | `qwen_image_2.1_int8_convrot.safetensors` | 换服饰独立主模型 |
| `models/text_encoders/` | `qwen3vl_8b_int8_convrot.safetensors` | 推荐工作流的文本/图像编码器 |
| `models/vae/` | `qwen_image_2.1_vae_bf16.safetensors` | Qwen Image 2.1 VAE |
| `models/loras/qwen-image2.1/` | `VNCCS_QI2_PoseStudioV1.1.safetensors` | 姿势 LoRA |

可选配置：

- `qwen3vl_8b_bf16.safetensors`：部分旧节点默认值使用 bf16 编码器。
- `VNCCS_QI2_PoseStudioV2.safetensors`：姿势跟随更强，但更容易改变原服装。
- Qwen-Image-Edit 2511 与其他版本模型：使用前请核对本项目节点默认文件名和上游许可证。

## 上游链接

- ComfyUI：https://github.com/comfyanonymous/ComfyUI
- Qwen-Image-2.1 ComfyUI 权重：https://huggingface.co/Comfy-Org/Qwen-Image-2.1
- Qwen-Image-Edit ComfyUI 权重：https://huggingface.co/Comfy-Org/Qwen-Image-Edit_ComfyUI
- Qwen3-VL：https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct
- 姿势 LoRA：https://huggingface.co/MIUProject/VNCCS_PoseStudio_QI2.1

链接和仓库名称可能变化。若文件不存在，请以对应 ComfyUI 节点显示的文件名和模型卡为准。

## 发布者注意

- 不要把 `.safetensors`、`.ckpt`、`.pt` 或 `.pth` 权重提交到本仓库，除非确认许可证明确允许再分发。
- 不要因为模型可以免费下载就认为可以随插件重新打包。
- 不要承诺生成结果一定可商用。
- 如提供在线生成服务，还需单独检查模型许可证中的服务、用户内容和输出条款。
