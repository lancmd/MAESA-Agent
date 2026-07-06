# PyTorch 土地利用分类执行规范

## 模型包

一个可执行模型必须作为完整目录上传：

```text
model_package/
├── model_config.json
├── model.pt2
└── model_card.md
```

优先使用 `torch.export.save` 生成的 `.pt2`；兼容已有 TorchScript `.pt`。不直接加载来源不明的完整 Python pickle。若用户只有 `state_dict`，应由模型作者在可信环境中提供网络结构并导出为 `.pt2`。

`model_config.json` 必须固定传感器、波段顺序、归一化、分辨率、patch、类别编码和模型文件哈希。模板见 `templates/pytorch_model_config.json`。

## 类别策略

推荐模型输出高潜水位七类全集。普通矿区在推理后将沉陷积水与自然水体合并，而不是临时改变模型输出通道。新增模型未训练过的类别时必须重新训练或微调。

## 推理

1. 确认输入影像的传感器、波段、比例因子和分辨率与模型配置一致。
2. 运行 `validate-model`；文件哈希、类别和预处理不完整时停止。
3. 按 patch 分块推理，以重叠权重融合接缝。
4. 输出分类 GeoTIFF、最大概率置信度 GeoTIFF 和运行报告。
5. 低置信度像元保留原类别，但加入复核掩膜；不得无依据地改成背景。

```powershell
python scripts/pytorch_lulc.py validate-model --model-package <模型目录>
python scripts/pytorch_lulc.py infer --model-package <模型目录> `
  --input-raster <多波段影像.tif> --class-output <分类.tif> `
  --confidence-output <置信度.tif> --device auto
```

## 科研验收

- 报告模型版本、训练区域、训练年份和传感器；
- 输入波段顺序与模型配置完全一致；
- 使用独立验证样本输出混淆矩阵、总体精度、F1/IoU 和分地类精度；
- 跨矿区直接迁移时把精度状态标记为 `pending_validation`；
- 输出类别编码与 `config/landuse_classes.md` 一致；
- 沉陷积水在基础推理后再结合工作面、沉陷范围、历史新增水体和低洼地形筛选。
