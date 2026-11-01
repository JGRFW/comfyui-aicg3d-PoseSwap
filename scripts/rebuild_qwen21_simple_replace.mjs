import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const workflowPath = path.resolve(
  scriptDir,
  "../example_workflows/aicg3d_qwen21_simple_replace.json",
);
const workflow = JSON.parse(fs.readFileSync(workflowPath, "utf8"));
const subgraph = workflow.definitions.subgraphs.find(
  (item) => item.id === "22222222-2222-4222-8222-222222222222",
);

if (!subgraph) {
  throw new Error("Replacement subgraph not found");
}

const titles = Object.fromEntries(
  subgraph.nodes
    .filter((node) => node.title)
    .map((node) => [node.type, node.title]),
);

const widgetInput = (name, type = "COMBO") => ({
  name,
  type,
  widget: { name },
  link: null,
});

const modelOutput = (links) => ({
  name: "MODEL",
  type: "MODEL",
  links,
});

function unetLoader({ id, pos, links, name, title }) {
  return {
    id,
    type: "UNETLoader",
    pos,
    size: [420, 90],
    flags: {},
    order: id - 1,
    mode: 0,
    inputs: [
      widgetInput("unet_name"),
      widgetInput("weight_dtype"),
    ],
    outputs: [modelOutput(links)],
    properties: { "Node name for S&R": "UNETLoader" },
    title,
    widgets_values: [name, "default"],
  };
}

function clipLoader({ id, pos, links, title }) {
  return {
    id,
    type: "CLIPLoader",
    pos,
    size: [420, 120],
    flags: {},
    order: id - 1,
    mode: 0,
    inputs: [
      widgetInput("clip_name"),
      widgetInput("type"),
      { ...widgetInput("device"), shape: 7 },
    ],
    outputs: [{ name: "CLIP", type: "CLIP", links }],
    properties: { "Node name for S&R": "CLIPLoader" },
    title,
    widgets_values: ["qwen3vl_8b_int8_convrot.safetensors", "qwen_image", "default"],
  };
}

const nodes = [
  unetLoader({
    id: 1,
    pos: [-650, 20],
    links: [120, 121],
    name: "qwen\\qwen_image_2.1_bf16.safetensors",
    title: "Shared UNET",
  }),
  clipLoader({ id: 2, pos: [-650, 150], links: [122, 123], title: "Shared CLIP" }),
  {
    id: 3,
    type: "VAELoader",
    pos: [-650, 310],
    size: [420, 70],
    flags: {},
    order: 2,
    mode: 0,
    inputs: [widgetInput("vae_name")],
    outputs: [{ name: "VAE", type: "VAE", links: [124, 125, 126] }],
    properties: { "Node name for S&R": "VAELoader" },
    title: "Shared VAE",
    widgets_values: ["qwen_image_2.1_vae_bf16.safetensors"],
  },
  {
    id: 4,
    type: "LoraLoaderModelOnly",
    pos: [-650, 420],
    size: [420, 130],
    flags: {},
    order: 3,
    mode: 0,
    inputs: [
      { name: "model", type: "MODEL", link: 120 },
      widgetInput("lora_name"),
      widgetInput("strength_model", "FLOAT"),
    ],
    outputs: [modelOutput([127])],
    properties: { "Node name for S&R": "LoraLoaderModelOnly" },
    title: "Pose LoRA",
    widgets_values: ["qwen-image2.1\\VNCCS_QI2_PoseStudioV1.1.safetensors", 1.0],
  },
  unetLoader({
    id: 5,
    pos: [-650, 590],
    links: [128],
    name: "qwen\\qwen_image_2.1_int8_convrot.safetensors",
    title: "Outfit UNET",
  }),
  clipLoader({ id: 6, pos: [-650, 720], links: [129], title: "Outfit CLIP" }),
  {
    id: 7,
    type: "PoseQwen21FaceStage",
    pos: [0, 20],
    size: [390, 330],
    flags: {},
    order: 6,
    mode: 0,
    inputs: [
      { name: "person_image", type: "IMAGE", link: 100 },
      { name: "portrait_image", type: "IMAGE", link: 101 },
      { name: "model", type: "MODEL", link: 121 },
      { name: "clip", type: "CLIP", link: 122 },
      { name: "vae", type: "VAE", link: 124 },
      { name: "enable", type: "BOOLEAN", widget: { name: "enable" }, link: 105 },
      { name: "seed", type: "INT", widget: { name: "seed" }, link: 113 },
    ],
    outputs: [{ name: "IMAGE", type: "IMAGE", links: [130, 132] }],
    properties: { "Node name for S&R": "PoseQwen21FaceStage" },
    title: titles.PoseQwen21FaceStage,
    widgets_values: [true, 20261101],
  },
  {
    id: 8,
    type: "PoseQwen21PoseStage",
    pos: [470, 20],
    size: [390, 350],
    flags: {},
    order: 7,
    mode: 0,
    inputs: [
      { name: "person_image", type: "IMAGE", link: 130 },
      { name: "pose_image", type: "IMAGE", link: 102 },
      { name: "model", type: "MODEL", link: 127 },
      { name: "clip", type: "CLIP", link: 123 },
      { name: "vae", type: "VAE", link: 125 },
      { name: "enable", type: "BOOLEAN", widget: { name: "enable" }, link: 106 },
      { name: "seed", type: "INT", widget: { name: "seed" }, link: 114 },
    ],
    outputs: [{ name: "IMAGE", type: "IMAGE", links: [131, 133] }],
    properties: { "Node name for S&R": "PoseQwen21PoseStage" },
    title: titles.PoseQwen21PoseStage,
    widgets_values: [true, 20261029],
  },
  {
    id: 9,
    type: "PoseQwen21OutfitStage",
    pos: [940, 20],
    size: [450, 480],
    flags: {},
    order: 8,
    mode: 0,
    inputs: [
      { name: "person_image", type: "IMAGE", link: 131 },
      { name: "garment_image", type: "IMAGE", link: 103 },
      { name: "model", type: "MODEL", link: 128 },
      { name: "clip", type: "CLIP", link: 129 },
      { name: "vae", type: "VAE", link: 126 },
      { name: "enable", type: "BOOLEAN", widget: { name: "enable" }, link: 107 },
      { name: "width", type: "INT", widget: { name: "width" }, link: 108 },
      { name: "height", type: "INT", widget: { name: "height" }, link: 109 },
      { name: "steps", type: "INT", widget: { name: "steps" }, link: 110 },
      {
        name: "sampler_name",
        type: "COMBO",
        widget: { name: "sampler_name" },
        link: 111,
      },
      {
        name: "scheduler",
        type: "COMBO",
        widget: { name: "scheduler" },
        link: 112,
      },
      { name: "seed", type: "INT", widget: { name: "seed" }, link: 115 },
      { name: "garment_description", type: "STRING", link: 104 },
    ],
    outputs: [{ name: "IMAGE", type: "IMAGE", links: [134] }],
    properties: { "Node name for S&R": "PoseQwen21OutfitStage" },
    title: titles.PoseQwen21OutfitStage,
    widgets_values: [true, 0, 0, 20, "euler", "simple", 20261101],
  },
];

const link = (id, originId, originSlot, targetId, targetSlot, type) => ({
  id,
  origin_id: originId,
  origin_slot: originSlot,
  target_id: targetId,
  target_slot: targetSlot,
  type,
});

const links = [
  link(100, -10, 0, 7, 0, "IMAGE"),
  link(101, -10, 1, 7, 1, "IMAGE"),
  link(102, -10, 2, 8, 1, "IMAGE"),
  link(103, -10, 3, 9, 1, "IMAGE"),
  link(104, -10, 4, 9, 12, "STRING"),
  link(105, -10, 5, 7, 5, "BOOLEAN"),
  link(106, -10, 6, 8, 5, "BOOLEAN"),
  link(107, -10, 7, 9, 5, "BOOLEAN"),
  link(108, -10, 8, 9, 6, "INT"),
  link(109, -10, 9, 9, 7, "INT"),
  link(110, -10, 10, 9, 8, "INT"),
  link(111, -10, 11, 9, 9, "COMBO"),
  link(112, -10, 12, 9, 10, "COMBO"),
  link(113, -10, 13, 7, 6, "INT"),
  link(114, -10, 13, 8, 6, "INT"),
  link(115, -10, 13, 9, 11, "INT"),
  link(120, 1, 0, 4, 0, "MODEL"),
  link(121, 1, 0, 7, 2, "MODEL"),
  link(122, 2, 0, 7, 3, "CLIP"),
  link(123, 2, 0, 8, 3, "CLIP"),
  link(124, 3, 0, 7, 4, "VAE"),
  link(125, 3, 0, 8, 4, "VAE"),
  link(126, 3, 0, 9, 4, "VAE"),
  link(127, 4, 0, 8, 2, "MODEL"),
  link(128, 5, 0, 9, 2, "MODEL"),
  link(129, 6, 0, 9, 3, "CLIP"),
  link(130, 7, 0, 8, 0, "IMAGE"),
  link(131, 8, 0, 9, 0, "IMAGE"),
  link(132, 7, 0, -20, 0, "IMAGE"),
  link(133, 8, 0, -20, 1, "IMAGE"),
  link(134, 9, 0, -20, 2, "IMAGE"),
];

subgraph.state.lastNodeId = 9;
subgraph.state.lastLinkId = 134;
subgraph.nodes = nodes;
subgraph.links = links;
subgraph.inputs = subgraph.inputs.map((item, index) => ({
  ...item,
  pos: [-650, 40 + index * 34],
}));
subgraph.outputs[0].linkIds = [132];
subgraph.outputs[1].linkIds = [133];
subgraph.outputs[2].linkIds = [134];
subgraph.outputs = subgraph.outputs.map((item, index) => ({
  ...item,
  pos: [1440, 60 + index * 80],
}));

const expectedStageTypes = [
  "PoseQwen21FaceStage",
  "PoseQwen21PoseStage",
  "PoseQwen21OutfitStage",
];
for (const type of expectedStageTypes) {
  const node = subgraph.nodes.find((item) => item.type === type);
  const hasModelInputs = ["model", "clip", "vae"].every((name) =>
    node?.inputs.some((input) => input.name === name)
  );
  const hasLegacyNameInputs = node?.inputs.some((input) =>
    ["unet_name", "clip_name", "vae_name"].includes(input.name)
  );
  if (!node || !hasModelInputs || hasLegacyNameInputs) {
    throw new Error(`Invalid model inputs on ${type}`);
  }
}
if (subgraph.nodes.some((node) => node.properties?.models)) {
  throw new Error("Custom model metadata remains in the replacement subgraph");
}
for (const item of subgraph.links) {
  const origin = item.origin_id === -10
    ? subgraph.inputs[item.origin_slot]
    : subgraph.nodes.find((node) => node.id === item.origin_id)?.outputs[item.origin_slot];
  const target = item.target_id === -20
    ? subgraph.outputs[item.target_slot]
    : subgraph.nodes.find((node) => node.id === item.target_id)?.inputs[item.target_slot];
  if (!origin || !target) {
    throw new Error(`Invalid link ${item.id}`);
  }
}

fs.writeFileSync(workflowPath, `${JSON.stringify(workflow, null, 2)}\n`, "utf8");
console.log(`Rebuilt ${workflowPath}`);
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 JGRFW
