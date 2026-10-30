import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// 服装选择节点：浏览内置服装图库按钮 + 服装预览（图库与路由均由本插件自带）
app.registerExtension({
  name: "comfyui-aicg3d-PoseSwap.garment",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== "PoseQwen21GarmentSelect") return;
    const created = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      created?.apply(this, arguments);
      const node = this;
      const value = node.widgets.find(w => w.name === "garment_id");
      let dialog, frame;
      const close = () => {
        window.removeEventListener("message", receive);
        dialog?.remove(); dialog = null; frame = null;
      };
      const previewBox = document.createElement("div");
      previewBox.style.cssText = "position:relative;width:100%;height:100%;background:#f8f7f3;border-radius:8px;overflow:hidden;";
      const preview = document.createElement("img");
      preview.alt = "所选服装预览";
      preview.style.cssText = "display:block;width:100%;height:100%;object-fit:contain;";
      const previewError = document.createElement("div");
      previewError.setAttribute("role", "status");
      previewError.setAttribute("aria-live", "polite");
      previewError.style.cssText = "display:none;position:absolute;inset:16px;place-items:center;color:#8b2e2e;font:14px/1.6 sans-serif;text-align:left;overflow-wrap:anywhere;";
      previewBox.append(preview, previewError);
      let previewRequest = 0;
      const update = () => {
        const request = ++previewRequest;
        const garmentId = String(value.value);
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
          previewError.textContent = `服装预览加载失败：/aicg3d_pose/garments/assets/${garmentId}.webp。请确认插件目录包含完整服装图库（garments/img/）。`;
        };
        preview.src = api.apiURL(`/aicg3d_pose/garments/assets/${encodeURIComponent(garmentId)}.webp`);
        preview.title = garmentId;
      };
      const previousCallback = value.callback;
      value.callback = function () { previousCallback?.apply(this, arguments); update(); };
      const receive = event => {
        if (event.origin !== location.origin || event.source !== frame?.contentWindow) return;
        if (event.data?.type === "aicg3d-garment-ready") {
          frame.contentWindow.postMessage({ type: "aicg3d-garment-current", id: value.value }, location.origin);
        }
        if (event.data?.type !== "aicg3d-garment-select" || typeof event.data.id !== "string") return;
        value.value = event.data.id;
        value.callback?.(value.value);
        node.setDirtyCanvas(true, true);
        app.graph.change();
        close();
      };
      node.addWidget("button", "浏览服装图库 · 分类 / 搜索", null, () => {
        if (dialog) return;
        dialog = document.createElement("dialog");
        dialog.style.cssText = "width:96vw;height:94vh;max-width:1800px;max-height:96vh;padding:0;border:1px solid #777;border-radius:12px;background:#f7f5ef;";
        const header = document.createElement("div");
        header.style.cssText = "height:48px;display:flex;align-items:center;justify-content:space-between;padding:0 20px;background:#e9efe9;color:#253c32;font:14px sans-serif;";
        const label = document.createElement("strong"); label.textContent = "AICG3D PoseSwap 服装图库 · 选择服装后点击「使用此服装」→ 输出服装图到换装生成节点";
        const done = document.createElement("button"); done.textContent = "关闭";
        done.style.cssText = "cursor:pointer;padding:6px 16px;border-radius:6px;border:1px solid #bac9bd;background:white;color:#253c32;";
        done.onclick = close; header.append(label, done);
        frame = document.createElement("iframe");
        frame.src = api.apiURL("/aicg3d_pose/garments/gallery");
        frame.title = "服装参考图库";
        frame.style.cssText = "width:100%;height:calc(100% - 48px);border:0;";
        dialog.append(header, frame);
        window.addEventListener("message", receive);
        dialog.addEventListener("cancel", event => { event.preventDefault(); close(); });
        dialog.addEventListener("click", event => { if (event.target === dialog) close(); });
        document.body.append(dialog); dialog.showModal();
      }, { serialize: false });
      node.addDOMWidget("garment_preview", "image", previewBox, { serialize: false, hideOnZoom: false, getMinHeight: () => 280, getMaxHeight: () => 460 });
      const configured = node.onConfigure;
      node.onConfigure = function () { configured?.apply(this, arguments); update(); };
      const removed = node.onRemoved;
      node.onRemoved = function () { close(); removed?.apply(this, arguments); };
      node.setSize([340, 380]); update();
    };
  },
});
