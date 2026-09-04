# 纯合成多期分类—InVEST 回归样例

这是一个由固定随机种子生成的小栅格合同测试：六期合成影像分别配置合成 ROI 与合成验证样本，用于检查分类、InVEST Carbon 和 Habitat Quality 数据栈接口。它不对应任何真实地区，也不包含真实边界、观测影像、训练样本或研究结论。

先生成数据并检查编译结果：

```powershell
& .\.venv\Scripts\python.exe .\examples\synthetic_multiperiod\synthetic_data.py
& .\.venv\Scripts\python.exe .\scripts\project_validator.py --project .\examples\synthetic_multiperiod\project.json
& .\.venv\Scripts\python.exe .\scripts\project_workflow.py --project .\examples\synthetic_multiperiod\project.json
```

真实项目应保留同样的结构，但每一期需要各自的训练 ROI 与独立验证样本。验证 CSV 使用 `reference,x,y` 和明确 CRS；流程会从生成的 LULC 栅格重新采样预测类别，而不会接受 CSV 中的预填预测值。碳密度、威胁因子、最大影响距离、权重和敏感性参数须由研究者提供。示例中的全部系数仅用于测试接口，不可用于生态学解释。

生成的输入与运行目录被忽略，不会提交至仓库。
