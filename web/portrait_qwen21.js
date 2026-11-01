import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

app.registerExtension({
  name: "comfyui-aicg3d-PoseSwap.portrait",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== "PoseQwen21PortraitSelect") return;
    const created = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      created?.apply(this, arguments);
      const node = this;
      const value = node.widgets.find(widget => widget.name === "portrait_id");
      let dialog, frame, previewRequest = 0;
      const close = () => {
        window.removeEventListener("message", receive);
        dialog?.remove();
        dialog = null;
        frame = null;
      };
      const previewBox = document.createElement("div");
      previewBox.style.cssText = "position:relative;width:100%;height:100%;background:#f7f5f0;border-radius:8px;overflow:hidden;";
      const preview = document.createElement("img");
      preview.alt = "所选换头换脸参考预览";
      preview.style.cssText = "display:block;width:100%;height:100%;object-fit:contain;";
      const previewError = document.createElement("div");
      previewError.setAttribute("role", "status");
      previewError.style.cssText = "display:none;position:absolute;inset:16px;place-items:center;color:#8b2e2e;font:13px/1.7 sans-serif;text-align:left;overflow-wrap:anywhere;";
      previewBox.append(preview, previewError);
      const update = () => {
        const request = ++previewRequest;
        const portraitId = String(value.value);
        preview.style.display = "block";
        previewError.style.display = "none";
        preview.onload = () => {
          if (request !== previewRequest) return;
          preview.style.display = "block";
          previewError.style.display = "none";
        };
        preview.onerror = () => {
          if (request !== previewRequest) return;
          preview.style.display = "none";
          previewError.style.display = "grid";
          previewError.textContent = "人像图库未安装或路径不完整。请确认 portraits/data/portrait-zh.json 存在，或运行 scripts/configure_portrait_library.py 配置图库目录。";
        };
        preview.src = api.apiURL(`/aicg3d_pose/portraits/thumb/${encodeURIComponent(portraitId)}.webp`);
        preview.title = portraitId;
      };
      const previousCallback = value.callback;
      value.callback = function () {
        previousCallback?.apply(this, arguments);
        update();
      };
      const receive = event => {
        if (event.origin !== location.origin || event.source !== frame?.contentWindow) return;
        if (event.data?.type === "aicg3d-portrait-ready") {
          frame.contentWindow.postMessage({ type: "aicg3d-portrait-current", id: value.value }, location.origin);
        }
        if (event.data?.type !== "aicg3d-portrait-select" || typeof event.data.id !== "string") return;
        if (!/^[a-z0-9_-]{1,80}$/i.test(event.data.id)) return;
        value.value = event.data.id;
        value.callback?.(value.value);
        node.setDirtyCanvas(true, true);
        app.graph.change();
        close();
      };
      node.addWidget("button", "浏览人像图库 · 正脸 / 造型 / 发型", null, () => {
        if (dialog) return;
        dialog = document.createElement("dialog");
        dialog.style.cssText = "width:96vw;height:94vh;max-width:1800px;max-height:96vh;padding:0;border:1px solid #777;border-radius:12px;background:#f7f5ef;";
        const header = document.createElement("div");
        header.style.cssText = "height:48px;display:flex;align-items:center;justify-content:space-between;gap:14px;padding:0 20px;background:#e9ecdf;color:#253c32;font:13px sans-serif;";
        const label = document.createElement("strong");
        label.textContent = "AICG3D 换头换脸参考 · 非官方本地索引 · 原作者 あぎ · 选择后回传 ComfyUI";
        const done = document.createElement("button");
        done.textContent = "关闭";
        done.style.cssText = "cursor:pointer;padding:6px 16px;border-radius:6px;border:1px solid #bac9bd;background:white;color:#253c32;";
        done.onclick = close;
        header.append(label, done);
        frame = document.createElement("iframe");
        frame.src = api.apiURL("/aicg3d_pose/portraits/gallery");
        frame.title = "人像参考图库";
        frame.style.cssText = "width:100%;height:calc(100% - 48px);border:0;";
        dialog.append(header, frame);
        window.addEventListener("message", receive);
        dialog.addEventListener("cancel", event => {
          event.preventDefault();
          close();
        });
        dialog.addEventListener("click", event => {
          if (event.target === dialog) close();
        });
        document.body.append(dialog);
        dialog.showModal();
      }, { serialize: false });
      node.addDOMWidget("portrait_preview", "image", previewBox, {
        serialize: false,
        hideOnZoom: false,
        getMinHeight: () => 300,
        getMaxHeight: () => 500,
      });
      const configured = node.onConfigure;
      node.onConfigure = function () {
        configured?.apply(this, arguments);
        update();
      };
      const removed = node.onRemoved;
      node.onRemoved = function () {
        close();
        removed?.apply(this, arguments);
      };
      node.setSize([350, 530]);
      update();
    };
  },
});
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 JGRFW
