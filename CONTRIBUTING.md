# Contributing

感谢提交改进。所有贡献都必须能够被清楚追溯来源和授权。

## 代码贡献

- 除非文件内另有说明，提交的源代码按根目录 MIT License 授权。
- 请保留既有版权、来源链接和 SPDX/许可声明。
- 不要复制许可不明的代码、HTML、CSS、图片、数据或模型权重。
- 提交前运行：

```bash
python -m py_compile __init__.py pose_data.py garment_data.py portrait_data.py
node --check web/pipeline_qwen21.js
node --check web/pose_qwen21.js
node --check web/garment_qwen21.js
node --check web/portrait_qwen21.js
```

## 图片、数据和模型

新增素材必须同时提供：

- 原始来源 URL
- 作者或权利人
- 许可证名称和链接
- 是否允许商业使用
- 是否允许再分发和修改
- 取得授权的证明（如适用）

无法确认来源或再分发权的素材不会被合并进公开仓库。不要提交从搜索引擎、社交媒体、电商页面或图库站点批量抓取且没有明确许可的图片。

## 提交信息

建议说明：

- 改动目的
- 涉及的用户行为
- 是否包含第三方素材
- 已运行的验证

通过提交 Pull Request，即表示你有权提交该贡献，并同意代码部分按 MIT License 发布。该同意不改变任何第三方素材、模型或商标原有的权利归属。
