# ENVI 监督分类流程

本文件用于指导矿区多波段影像在 ENVI 中完成监督分类。界面名称以 ENVI 6.2 为参考，旧版本可能略有差异。

## 目录

1. 输入检查
2. 训练数据
3. 方法选择
4. 分类参数
5. 后处理与输出

## 1. 输入检查

输入通常为 `gee_codes/` 生成的 GeoTIFF。分类前检查：

- 影像范围、投影、像元大小和 NoData 是否正确；
- 波段顺序和名称是否与导出脚本一致；
- 是否存在全黑、条带、残云或明显拼接缝；
- 多期分类是否使用一致的波段、季节、分类编码和空间网格；
- 指数波段与反射率波段是否均为连续数值，且未被错误拉伸后保存。

推荐输入波段：

| 数据源 | 推荐特征 |
|---|---|
| Landsat | Blue、Green、Red、NIR、SWIR1、SWIR2、NDVI、NDWI、MNDWI、NDBI |
| Sentinel-2 | Blue、Green、Red、NIR、SWIR1、SWIR2、NDVI、NDWI、MNDWI、NDBI |

先显示真彩色 `Red/Green/Blue` 和假彩色 `NIR/Red/Green`，结合高分辨率影像检查地物。

## 2. 训练数据

使用 ROI Tool 创建或载入训练样本。普通矿区采用六类，高潜水位煤矿区采用七类，编码必须与 `config/landuse_classes.md` 一致。

训练 ROI 与验证 ROI 必须独立。先固定验证样本，再调分类器，避免把验证集变成调参训练集。详细规则见 `roi_sample_rules.md`。

## 3. 方法选择

“最大最小分类”不是一个算法，本模块将其拆分为最大似然法和最小距离法。建议用同一训练集和验证集运行多种方法，再按混淆矩阵选择。

| 方法 | 推荐场景 | 主要限制 |
|---|---|---|
| Random Forest | 类别关系复杂、特征较多、样本较充足 | 需安装 ENVI Machine Learning；应控制类别不平衡 |
| SVM | 样本中等、类别边界复杂 | 大 ROI 可能耗时；参数需验证 |
| Maximum Likelihood | 各类近似正态且协方差估计稳定 | 每类样本必须明显多于特征数；对混合样本敏感 |
| Minimum Distance | 快速基线、样本较少或旧版 ENVI | 忽略类内协方差；对特征尺度和类间重叠敏感 |

不要把算法名称当作精度保证。沉陷积水与自然水体若缺少历史和采矿背景信息，任何像元分类器都可能混淆。

## 4. 分类参数

### 4.1 Random Forest

路径：`Toolbox → Machine Learning → Supervised → Random Forest Classification`

建议从以下设置开始：

- Estimators：100；如结果不稳定，再比较 200 或更多树；
- Max Features：`sqrt`；
- Balance Classes：小类别明显不足时设为 Yes；
- OOB：设为 Yes 可辅助诊断泛化表现，但不能替代独立验证；
- Output Raster：保存最终单波段分类图；
- Output Model：保存模型，便于同类影像复用。

Machine Learning 工具是单独安装组件；若当前 ENVI 未安装该组件，使用传统分类器或安装匹配版本的组件。

### 4.2 SVM

路径：`Toolbox → Classification → Supervised Classification → Support Vector Machine Classification`

- 先以 Radial Basis Function 为候选核；
- 不要默认某组 Gamma 和 Penalty 对所有矿区都最佳；
- 用固定验证集比较参数，关注小类别用户精度和生产者精度；
- 大面积 ROI 可能显著增加运行时间，可减少冗余样本而不是删掉空间代表性。

### 4.3 Maximum Likelihood

路径：`Toolbox → Classification → Supervised Classification → Maximum Likelihood Classification`

- 先检查每类样本是否足以估计协方差矩阵；
- Threshold Probability 为 0 时通常会把所有有效像元分到某类；
- 提高阈值会增加未分类像元，应结合误分与漏分权衡；
- 保存 Output Raster；Rule Raster 仅用于查看每类判别值。

### 4.4 Minimum Distance

路径：`Toolbox → Classification → Supervised Classification → Minimum Distance Classification`

- 该方法按像元到各类均值向量的欧氏距离分类；
- 未设置阈值时，所有有效像元都会被分到最近类别；
- Maximum Distance 和 Standard Deviation 阈值越小，未分类像元通常越多；
- 指数与反射率尺度差异可能影响距离，比较前确认特征尺度合理；
- 将其作为快速基线，不应在未评价精度时直接作为最终结果。

## 5. 分类比较与后处理

为每种候选方法记录：算法、参数、训练样本版本、总体精度、各类用户精度、各类生产者精度和未分类比例。使用 `accuracy_assessment.md` 中的同一验证集评价。

分类后可使用 Majority/Minority、Sieve Classes 和 Clump Classes 减少椒盐噪声，但必须：

- 保存未经后处理的原始分类图；
- 记录窗口和最小斑块阈值；
- 避免抹除窄河流、小型沉陷水面、道路和小型工矿斑块；
- 后处理后重新进行精度评价。

最终至少保存：分类栅格、ROI 文件、参数记录、混淆矩阵、类别编码表和必要的 Rule Raster。最终土地利用图必须是 Classification Raster，而不是 Rule/Probability Raster。
