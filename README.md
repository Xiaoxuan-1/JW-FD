# JW-FlareDataset

基于 **HMI 磁图** 与 **NOAA/SRS、Events** 数据，从全日面 FITS 裁剪活动区、提取磁图特征，并结合耀斑事件表构建多阈值、多预测窗口的太阳耀斑数据集（CSV + 可选 PNG / 视频）。

本仓库主要提供**数据集构造流程代码**；约 **1/10** 抽样子集（FITS + PNG Th1000 + movies + 标签，按 AR 对齐）可通过下方链接下载。完整版计划后续发布至国家天文数据中心（NADC）。

## 数据下载（10% 子集）

| 渠道 | 链接 | 说明 |
|------|------|------|
| **Zenodo** | [DOI: 10.5281/zenodo.21672850](https://doi.org/10.5281/zenodo.21672850) · [记录页](https://zenodo.org/records/21672850) | 分卷 `JW-FD_subset_10pct.tar.zst.*.part`（约 4 GiB/卷）+ 合包说明 |
| **百度网盘** | [分享链接](https://pan.baidu.com/s/1POxKrHRjtF_ZEF2Yb5H2Og)（提取码：`gmsm`） | 目录 `/JW-FD/JW-FD_subset_10pct/`，约 166 GB；分享有效期至 **2026-08-27** |

### Zenodo 合包与解压

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
| 3 | `step3_convert_to_png.py` | 裁剪 FITS → PNG（磁场阈值由 `mag_threshold` 决定输出目录名） |
| 4 | `step4_generate_dataset_fits.py` | 从 FITS 提取 **29 维**特征 + 标签 → `solar_flare_dataset_fits_{suffix}.csv` |
| 5 | `step5_generate_dataset_png.py` | 从 PNG 提取特征 + 标签 → `solar_flare_dataset_png_{suffix}.csv` |
| 6 | `step6_make_movie.py` | 按活动区 PNG 序列生成演化视频（`movies_600_Th{mag_threshold}`） |

入口：

- **非交互 / 适合 `nohup`**：`python run_pipeline.py [起始步] [结束步]`  
- **交互菜单**：`python main_pipeline.py`

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
| `START_YEAR` / `END_YEAR` | 参与处理的日历年；Step3–6 会按文件名中的 `YYYYMMDD` 过滤 |
| `PARAMS['mag_threshold']` | 磁图归一化阈值（如 200 / 500 / 1000），影响 PNG 与 movies 子目录名 |
| `PARAMS['prediction_hours']` | 预测窗口（小时），可为单个 `int` 或 `list[int]`，与多列标签对应 |
| `PARAMS['max_latitude']` / `max_longitude']` | Step2 日面位置筛选 |
| `FLARE_LABEL_THRESHOLDS` | 多阈值二分类列，默认 `C1.0, M1.0, M5.0, X1.0` |

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

## 常用命令

```bash
# 全流程
python run_pipeline.py

# 仅 Step 1–3
python run_pipeline.py 1 3

# 仅 Step 4
python run_pipeline.py 4 4

# 后台示例
nohup python run_pipeline.py 4 5 > pipeline_step45.log 2>&1 &
```

## 仓库说明

- 本仓库主要包含**代码**；大体积数据、日志未纳入版本控制（见 [`.gitignore`](.gitignore)）。
- 子集数据请见上方「数据下载」；完整版不在本仓库中。
- 本地备份目录 `2024_test_01-07/` 已忽略，不参与推送。

## 引用

若使用本仓库或 JW-FD 子集数据进行研究，请引用本仓库，并视情况引用 Zenodo 数据集：

```
https://github.com/Xiaoxuan-1/JW-FD
https://doi.org/10.5281/zenodo.21672850
```
