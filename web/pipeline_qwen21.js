import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const LABELS = {
  enable_face: "换头像开关",
  enable_pose: "换姿势开关",
  enable_outfit: "换服饰开关",
  width: "自定义宽度（0 = 原比例）",
  height: "自定义高度（0 = 原比例）",
  steps: "换服饰步数",
  sampler_name: "采样器",
  scheduler: "调度器",
  seed: "随机种",
  face_unet_name: "换头像模型",
  face_clip_name: "换头像编码器",
  pose_unet_name: "换姿势模型",
  pose_clip_name: "换姿势编码器",
  pose_lora_name: "换姿势 LoRA",
  outfit_unet_name: "换服饰模型",
  outfit_clip_name: "换服饰编码器",
  vae_name: "VAE",
};

const ADVANCED_WIDGETS = [
  "face_unet_name",
  "face_clip_name",
  "pose_unet_name",
  "pose_clip_name",
  "pose_lora_name",
  "outfit_unet_name",
  "outfit_clip_name",
  "vae_name",
];

const STAGE_META = [
  ["face", "换头像"],
  ["pose", "换姿势"],
  ["outfit", "换服饰"],
];

function createPreviewPanel(node) {
  const panel = document.createElement("div");
  panel.style.cssText = "display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;width:100%;height:100%;padding:6px;box-sizing:border-box;background:#162126;border-radius:8px;";
  const images = {};

  for (const [stage, label] of STAGE_META) {
    const pane = document.createElement("div");
    pane.style.cssText = "display:flex;flex-direction:column;min-width:0;min-height:0;border:1px solid #34464e;border-radius:6px;background:#0d1518;overflow:hidden;";
    const heading = document.createElement("div");
    heading.textContent = label;
    heading.style.cssText = "flex:0 0 26px;display:flex;align-items:center;justify-content:center;color:#dbe9ee;background:#22343b;font:12px sans-serif;";
    const image = document.createElement("img");
    image.alt = `${label}结果预览`;
    image.style.cssText = "display:block;width:100%;height:calc(100% - 26px);object-fit:contain;background:#0d1518;";
    pane.append(heading, image);
    panel.append(pane);
    images[stage] = image;
  }

  node.__aicg3dStageImages = images;
  node.addDOMWidget("aicg3d_stage_previews", "previews", panel, {
    serialize: false,
    hideOnZoom: false,
    getMinHeight: () => 230,
    getMaxHeight: () => 360,
  });
}

function updateStagePreview(event) {
  const detail = event.detail;
  if (!detail?.node_id || !detail?.stage || !detail?.filename) return;
  const node = app.graph?._nodes?.find((item) => String(item.id) === String(detail.node_id));
  const image = node?.__aicg3dStageImages?.[detail.stage];
  if (!image) return;
  const params = new URLSearchParams({
    filename: detail.filename,
    subfolder: detail.subfolder ?? "",
    type: detail.type ?? "temp",
    rand: String(Date.now()),
  });
  image.src = api.apiURL(`/view?${params.toString()}`);
}

app.registerExtension({
  name: "comfyui-aicg3d-PoseSwap.sequential-preview",
  setup() {
    api.addEventListener("aicg3d-stage-preview", updateStagePreview);
    api.addEventListener("execution_start", () => {
      for (const node of app.graph?._nodes ?? []) {
        for (const image of Object.values(node.__aicg3dStageImages ?? {})) {
          image.removeAttribute("src");
        }
      }
    });
  },
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== "PoseQwen21SequentialEdit") return;

    const created = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      created?.apply(this, arguments);

      for (const [name, label] of Object.entries(LABELS)) {
        const widget = this.widgets?.find((item) => item.name === name);
        if (widget) widget.label = label;
      }

      const seedControl = this.widgets?.find(
        (item) => item.name === "control_after_generate"
      );
      if (seedControl) seedControl.hidden = true;

      const advanced = ADVANCED_WIDGETS
        .map((name) => this.widgets?.find((item) => item.name === name))
        .filter(Boolean);
      let expanded = false;
      for (const widget of advanced) widget.hidden = true;

      const toggle = this.addWidget("button", "显示高级模型设置", null, () => {
        expanded = !expanded;
        for (const widget of advanced) widget.hidden = !expanded;
        toggle.name = expanded ? "收起高级模型设置" : "显示高级模型设置";
        toggle.label = toggle.name;
        this.setSize([560, expanded ? 820 : 650]);
        this.setDirtyCanvas(true, true);
      }, { serialize: false });

      createPreviewPanel(this);
      this.color = "#24333a";
      this.bgcolor = "#10191d";
      this.setSize([560, 650]);
    };
  },
});
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 JGRFW
