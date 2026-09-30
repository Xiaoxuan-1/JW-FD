# JW-FD

基于 **HMI 磁图** 与 **NOAA/SRS、Events** 数据，从全日面 FITS 裁剪活动区、提取磁图特征，并结合耀斑事件表构建多阈值、多预测窗口的太阳耀斑数据集（CSV + 可选 PNG / 视频）。

本仓库是 Universe 论文的开源构建流水线：<https://github.com/Xiaoxuan-1/JW-FD>。

论文：[JW-FD: A Long Horizon Multimodal Solar Flare Forecasting Dataset](https://arxiv.org/abs/2608.19195)（arXiv:2608.19195）

## 数据发布

| 版本 | 内容 | 获取方式 |
|------|------|----------|
| Zenodo **v1** | 约 10% 代表性子集 | [doi:10.5281/zenodo.21672850](https://doi.org/10.5281/zenodo.21672850) · [记录页](https://zenodo.org/records/21672850) |
| Zenodo **v2** | 完整 15 年释放（同一条 Zenodo 记录） | 即将发布；DOI 签发后写在本 README |
| 百度网盘 | [分享链接](https://pan.baidu.com/s/1TxJPOqVKGdU2B8bkblL1XA)（提取码：`gmsm`） | 目前提供 v1 子集目录 `/JW-FD/JW-FD_subset_10pct/`，约 166 GB |

覆盖 **2011-01-01 至 2025-12-31**。PNG 默认工作点 **800 G**；十档饱和阈值 **200–2000 G，步长 200 G**。官方划分是活动区级 8:1:1 **分层拒绝采样，seed=3970**。冻结的 AR 成员名单见 [`split_v2_ar_membership.json`](split_v2_ar_membership.json)。

Zenodo v1 分卷合包：

```bash
cat JW-FD_subset_10pct.tar.zst.*.part > JW-FD_subset_10pct.tar.zst
zstd -t JW-FD_subset_10pct.tar.zst
tar -I zstd -xf JW-FD_subset_10pct.tar.zst
```

## 流水线概览

| Step | 脚本 | 说明 |
|------|------|------|
| 1 | `step1_extract_flare_labels.py` | 从 NOAA Events（XRA）提取耀斑记录 → `flare_labels.csv`（含 Begin / Max / End 时间与等级） |
| 2 | `step2_crop_active_regions.py` | 按 SRS 位置与 HMI 全日面 FITS 裁剪 **600×600** 活动区子图 |
| 3 | `step3_convert_to_png.py` | 裁剪 FITS → PNG。左右翻转后按固定 ±B_th 定标（NaN→0 G，0 G→灰阶 127） |
| 4 | `step4_generate_dataset_fits.py` | 从 FITS 提取 **29 维**特征 + 标签 → `solar_flare_dataset_fits_{suffix}.csv` |
| 5 | `step5_generate_dataset_png.py` | 从 PNG 提取特征 + 标签 → `solar_flare_dataset_png_{suffix}.csv` |
| 6 | `step6_make_movie.py` | 按活动区 PNG 序列生成演化视频（`movies_600_Th{mag_threshold}`） |

入口：

- **非交互 / 适合 `nohup`**：`python run_pipeline.py [起始步] [结束步]`  
- **交互菜单**：`python main_pipeline.py`
- **多阈值增量**：`python batch_update_thresholds.py`（默认十档 + seed 3970 名单划分）

## 环境依赖

建议使用 Python 3.9+，典型依赖包括：

`numpy`、`pandas`、`astropy`、`sunpy`、`tqdm`、`Pillow`、`scipy`、`scikit-image`、`imageio`（Step6 视频）等。请按本机环境安装；若 Step2 报 `sunpy` / `astropy` 相关导入错误，需检查二者版本是否匹配。

`run_pipeline.py` / `main_pipeline.py` 开头将临时目录设为 `TMPDIR`（可按机器路径修改），需保证该目录可写。

## 配置（[`config.py`](config.py)）

运行前请根据数据实际位置修改：

| 项 | 含义 |
|----|------|
| `DATA_ROOT` | 原始数据根（下含 `Labels`、`Fits` 等） |
| `OUTPUT_PATH` | 中间结果与 CSV、标签、日志输出根目录 |
| `START_YEAR` / `END_YEAR` | 默认 **2011–2025**；Step3–6 会按文件名中的 `YYYYMMDD` 过滤 |
| `PARAMS['mag_threshold']` | PNG 默认工作点 **800 G** |
| `PARAMS['png_thresholds']` | 十档：`200, 400, …, 2000` |
| `SPLIT_SEED` | 官方划分 **3970** |
| `PARAMS['prediction_hours']` | 预测窗口（小时），可为单个 `int` 或 `list[int]`，与多列标签对应 |
| `PARAMS['max_latitude']` / `PARAMS['max_longitude']` | Step2 日面位置筛选 |
| `FLARE_LABEL_THRESHOLDS` | 多阈值二分类列，默认 `C1.0, M1.0, M5.0, X1.0` |

PNG 定标：`NaN → 0 G`，`clip(B, -B_th, B_th)`，再 `(B + B_th) / (2 B_th) * 255` → `uint8`（0 G 对应灰阶 127）。

输出文件名后缀：`get_output_suffix()` → `Lat{lat}_Lon{lon}_Th{threshold}`。

### 原始数据目录约定（`Labels`）

- **SRS**：`{labels_root}/{year}/{year}_SRS` 或 `{labels_root}/{year}_SRS`
- **Events**：`{labels_root}/{year}/{year}_events` 或 `{labels_root}/{year}_events`

### HMI FITS（`Fits`）

由 `get_fits_folders()` 扫描的年月子目录结构；需与 `config` 中路径一致。

## 数据集 CSV 列结构

- **特征**：29 列，名称见 `FEATURE_NAMES`（[`config.py`](config.py)）。
- **标签**：对每个 `prediction_hours` 中的 `hr` 与每个 `FLARE_LABEL_THRESHOLDS` 中的阈值，生成 `flare_label_{thr}_{hr}hr`；对每个 `hr` 生成 `flare_class_{hr}hr`（该窗口内匹配事件的最强等级字符串）。
- **元数据**：`image_filename`、`image_path`。

FITS / PNG 两套 CSV 仅图像来源不同，列结构一致（文件名分别为 `solar_flare_dataset_fits_*` / `solar_flare_dataset_png_*`）。

当前实现中，**时间窗口与正样本语义**以 Step4/5 中 `get_flare_label` 为准（严格预测：半开区间 `[Begin_Time - hr, Begin_Time)`，爆发开始时刻及之后不计入该窗口正类；具体以代码为准）。

划分：

```bash
python split_dataset.py --input /path/to/solar_flare_dataset_png_Lat60_Lon60_Th800.csv
# 默认使用 split_v2_ar_membership.json（seed 3970）
```

## 常用命令

```bash
# 全流程
python run_pipeline.py

# 仅 Step 1–3
python run_pipeline.py 1 3

# 仅 Step 4
python run_pipeline.py 4 4

# 十档 PNG + CSV（默认 200–2000 G）
python batch_update_thresholds.py

# 后台示例
nohup python run_pipeline.py 4 5 > pipeline_step45.log 2>&1 &
```

## 仓库说明

- 本仓库主要包含**代码**与官方 AR 名单；大体积数据、日志未纳入版本控制（见 [`.gitignore`](.gitignore)）。
- 子集数据请见上方「数据发布」；完整 15 年数据将作为同一条 Zenodo 记录的 v2 发布。

## 论文

| 稿件 | 路径 | 状态 |
|------|------|------|
| SPIE Proceedings（ATI 2026, **14155-94**） | [`paper/SPIE/`](paper/SPIE/)（仓库内为快照） | **已发表，稿件冻结。最终版在中国科技云 Overleaf**（[latex.cstcloud.cn](https://latex.cstcloud.cn)；2026-09-01 记录） |
| MDPI *Universe* 期刊稿 | [`paper/universe/`](paper/universe/) | 进行中；数据条款以该稿为准（Zenodo v1 + 即将发布的 v2） |

SPIE 题目：*An end-to-end pipeline for multimodal solar flare forecasting dataset construction*。最后一次修改在中国科技云 Overleaf 完成，那里才是投稿/发表用的最终源稿；本仓库 `paper/SPIE/` 仅作本地快照，可能落后于 Overleaf。详情见 [`paper/SPIE/README.md`](paper/SPIE/README.md)。期刊稿请只改 `paper/universe/`。

## 引用

若使用本仓库或 JW-FD 数据进行研究，请引用论文，并视情况引用代码仓库与 Zenodo v1 子集。完整 15 年数据请等 v2 DOI 签发后再引用。

```bibtex
@misc{shao2026jwfd,
  title         = {{JW-FD}: A Long Horizon Multimodal Solar Flare Forecasting Dataset},
  author        = {Shao, Mingfu and Lin, Jiaben and Wang, Hui and Tong, Liyue and Yang, Chen and Zhang, Yin and Li, Yuyang},
  year          = {2026},
  eprint        = {2608.19195},
  archivePrefix = {arXiv},
  primaryClass  = {astro-ph.SR},
  url           = {https://arxiv.org/abs/2608.19195}
}
```

- 论文：https://arxiv.org/abs/2608.19195
- 代码：https://github.com/Xiaoxuan-1/JW-FD
- 数据（Zenodo v1，约 10% 子集）：https://doi.org/10.5281/zenodo.21672850
