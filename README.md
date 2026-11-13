# JW-FD

基于 **HMI 磁图** 与 **NOAA/SRS、Events** 数据，从全日面 FITS 裁剪活动区、提取磁图特征，并结合耀斑事件表构建多阈值、多预测窗口的太阳耀斑数据集（CSV + 可选 PNG / 视频）。

This repository builds a multi-threshold, multi-horizon solar-flare dataset from **HMI magnetograms** and **NOAA SRS / Events**. It crops active regions from full-disk FITS, extracts magnetic features, and joins them to the flare catalog (CSV, with optional PNG and movies).

本仓库是论文的开源构建流水线：<https://github.com/Xiaoxuan-1/JW-FD>。

Open-source construction pipeline for the paper: <https://github.com/Xiaoxuan-1/JW-FD>.

论文 / Paper：[JW-FD_V2: A 15-Year Multimodal Dataset for Solar Flare Forecasting](https://arxiv.org/abs/2608.19195)（arXiv:2608.19195）

## 数据发布 / Data release

| 版本 Version | 内容 Contents | 获取方式 Access |
|------|------|----------|
| Zenodo **v1** | 约 10% 代表性子集 / ~10% representative subset | [doi:10.5281/zenodo.21672850](https://doi.org/10.5281/zenodo.21672850) · [record](https://zenodo.org/records/21672850) |
| ScienceDB **v2** | 完整 15 年 / full 15 years | [doi:10.57760/sciencedb.019mg](https://doi.org/10.57760/sciencedb.019mg) |

覆盖 **2011-01-01 至 2025-12-31**。PNG 默认工作点 **800 G**；十档饱和阈值 **200–2000 G，步长 200 G**。官方划分是活动区级 8:1:1，seed=3970。冻结的 AR 成员名单见 [`split_v2_ar_membership.json`](split_v2_ar_membership.json)。

Coverage is **2011-01-01 through 2025-12-31**. The default PNG working point is **800 G**, with ten saturation thresholds from **200 to 2000 G in steps of 200 G**. The official split is an active-region-level 8:1:1 partition with seed 3970. The frozen membership list is [`split_v2_ar_membership.json`](split_v2_ar_membership.json).

Zenodo v1 分卷合包 / reassemble the split archive:

```bash
cat JW-FD_subset_10pct.tar.zst.*.part > JW-FD_subset_10pct.tar.zst
zstd -t JW-FD_subset_10pct.tar.zst
tar -I zstd -xf JW-FD_subset_10pct.tar.zst
```

## 流水线概览 / Pipeline

| Step | 脚本 Script | 说明 Description |
|------|------|------|
| 1 | `step1_extract_flare_labels.py` | 从 NOAA Events（XRA）提取耀斑记录 → `flare_labels.csv`（Begin / Max / End 与等级）。Extract XRA flare records from NOAA Events into `flare_labels.csv` (begin, max, end, and class). |
| 2 | `step2_crop_active_regions.py` | 按 SRS 位置从 HMI 全日面 FITS 裁 **600×600**，写入未旋转的 `fits_600_raw`。起点是最靠近日面中心的一帧。Crop **600×600** patches from full-disk HMI FITS at the SRS location into unrotated `fits_600_raw`. The seed frame is the one closest to disk center. |
| 2b | `step2b_rotate_fits.py` | 将 `fits_600_raw` 旋转 180° 写入 `fits_600`。HMI 全日面自带 180°，裁剪不改朝向。Rotate `fits_600_raw` by 180° into `fits_600`. Full-disk HMI is stored rotated; cropping does not change orientation. |
| 3 | `step3_convert_to_png.py` | rot180 后的 FITS 转 PNG：只做上下翻转，再按固定 ±B_th 定标（NaN→0 G，0 G→灰阶 127）。PNG from the rotated FITS: a vertical flip, then a fixed ±B_th scale (NaN→0 G, 0 G→gray 127). |
| 4 | `step4_generate_dataset_fits.py` | 从 FITS 提取 **29 维**特征与标签 → `solar_flare_dataset_fits_{suffix}.csv`。**29** features and labels from FITS → `solar_flare_dataset_fits_{suffix}.csv`. |
| 5 | `step5_generate_dataset_png.py` | 从 PNG 提取特征与标签 → `solar_flare_dataset_png_{suffix}.csv`。Features and labels from PNG → `solar_flare_dataset_png_{suffix}.csv`. |
| 6 | `step6_make_movie.py` | 按活动区 PNG 序列生成演化视频（`movies_600_Th{mag_threshold}`）。Evolution movies from each region's PNG sequence. |

入口 / Entry points：

- **非交互，适合 `nohup` / non-interactive:** `python run_pipeline.py [start] [end]`
- **交互菜单 / interactive menu:** `python main_pipeline.py`
- **十档阈值 / all ten thresholds:** `python batch_update_thresholds.py`（默认十档，并按 seed 3970 名单划分 / default ten thresholds, then the seed-3970 membership split）

## 环境 / Environment

```bash
conda env create -f environment.yml
conda activate JW-FD
```

临时文件写到环境变量 `TMPDIR`。未设置时用 `/tmp`。

Temporary files go to `TMPDIR`, or to `/tmp` when that variable is unset.

## 配置 / Configuration ([`config.py`](config.py))

运行前按本机数据位置修改。Set these to the paths on your machine before running.

| 项 Key | 含义 Meaning |
|----|------|
| `DATA_ROOT` | 原始数据根，下含 `Labels`、`Fits`。Raw-data root, with `Labels` and `Fits` underneath. |
| `OUTPUT_PATH` | 中间结果、CSV、标签和日志。Intermediate products, CSV, labels, and logs. |
| `START_YEAR` / `END_YEAR` | 默认 **2011–2025**。Step 3–6 按文件名中的 `YYYYMMDD` 过滤。Default **2011–2025**. Steps 3–6 filter on the `YYYYMMDD` in each filename. |
| `PARAMS['mag_threshold']` | PNG 默认工作点 **800 G**。Default PNG working point, **800 G**. |
| `PARAMS['png_thresholds']` | 十档 `200, 400, …, 2000`。The ten thresholds. |
| `SPLIT_SEED` | 官方划分 **3970**。Official split seed. |
| `PARAMS['prediction_hours']` | 预测窗口（小时），单个 `int` 或 `list[int]`，对应多列标签。Forecast horizons in hours, one `int` or a `list[int]`, one label column per horizon. |
| `PARAMS['max_latitude']` / `PARAMS['max_longitude']` | Step 2 的日面位置筛选。Disk-position cuts in Step 2. |
| `FLARE_LABEL_THRESHOLDS` | 多阈值二分类列，默认 `C1.0, M1.0, M5.0, X1.0`。Binary label thresholds. |

PNG 定标：`NaN → 0 G`，`clip(B, -B_th, B_th)`，再 `(B + B_th) / (2 B_th) * 255` → `uint8`（0 G 对应灰阶 127）。

PNG scaling: `NaN → 0 G`, `clip(B, -B_th, B_th)`, then `(B + B_th) / (2 B_th) * 255` as `uint8` (0 G maps to gray 127).

输出文件名后缀由 `get_output_suffix()` 生成：`Lat{lat}_Lon{lon}_Th{threshold}`。

The filename suffix comes from `get_output_suffix()`: `Lat{lat}_Lon{lon}_Th{threshold}`.

### 原始数据目录 / Raw data layout (`Labels`)

- **SRS**：`{labels_root}/{year}/{year}_SRS` 或 / or `{labels_root}/{year}_SRS`
- **Events**：`{labels_root}/{year}/{year}_events` 或 / or `{labels_root}/{year}_events`

### HMI FITS (`Fits`)

由 `get_fits_folders()` 扫描年月子目录，路径需与 `config` 一致。

`get_fits_folders()` scans the year/month subdirectories. Those paths must match `config`.

## 数据集 CSV / Dataset CSV

- **特征 / Features：** 29 列，名称见 `FEATURE_NAMES`（[`config.py`](config.py)）。29 columns, named in `FEATURE_NAMES`.
- **标签 / Labels：** 每个预测窗口 `hr`、每个阈值生成 `flare_label_{thr}_{hr}hr`；每个窗口另有 `flare_class_{hr}hr`（该窗口内最强等级）。For each horizon `hr` and each threshold, `flare_label_{thr}_{hr}hr`; each horizon also has `flare_class_{hr}hr` (the strongest class in that window).
- **元数据 / Metadata：** `image_filename`、`image_path`。

FITS 与 PNG 两套 CSV 只是图像来源不同，列结构相同（`solar_flare_dataset_fits_*` / `solar_flare_dataset_png_*`）。

The FITS and PNG CSV files differ only in the image source. Their columns match.

正样本按 Step 4/5 的 `get_flare_label`：半开区间 `[Begin_Time - hr, Begin_Time)`。爆发开始时刻及之后不计入该窗口的正类。

A frame is positive under `get_flare_label` in Steps 4 and 5 when the flare begins inside the half-open interval `[Begin_Time - hr, Begin_Time)`. The start time itself, and everything after it, is not a positive for that horizon.

划分 / Split:

```bash
python split_dataset.py --input /path/to/solar_flare_dataset_png_Lat60_Lon60_Th800.csv
# 默认 / default: split_v2_ar_membership.json (seed 3970)
```

## 常用命令 / Commands

```bash
# 全流程 / full pipeline
python run_pipeline.py

# 仅 Step 1–3 / steps 1–3 only
python run_pipeline.py 1 3

# 仅 Step 4 / step 4 only
python run_pipeline.py 4 4

# 十档 PNG 与 CSV（默认 200–2000 G）
# ten PNG thresholds and their CSV files (200–2000 G)
python batch_update_thresholds.py

# 后台 / background
nohup python run_pipeline.py 4 5 > pipeline_step45.log 2>&1 &
```

## 仓库说明 / What is in this repository

- 本仓库是**代码**和官方 AR 名单。大体量数据和日志不纳入版本控制（见 [`.gitignore`](.gitignore)）。This repository holds the **code** and the official AR membership list. The bulk data and logs are not versioned.
- 子集见上方「数据发布」。完整 15 年数据是 ScienceDB v2：https://doi.org/10.57760/sciencedb.019mg The subset is listed under Data release. The full 15-year release is ScienceDB v2.

## 论文 / Papers

| 稿件 Paper | 链接 Link | 状态 Status |
|------|------|------|
| arXiv 最新版 / latest preprint | [JW-FD_V2: A 15-Year Multimodal Dataset for Solar Flare Forecasting](https://arxiv.org/abs/2608.19195) | arXiv:2608.19195 |
| SPIE Proceedings（ATI 2026, 14155-94） | [doi:10.1117/12.3102831](https://doi.org/10.1117/12.3102831) | 已发表 / published（Proc. SPIE **14155**, 2026-08-19） |
| MDPI *Universe* | [doi:10.3390/universe12090281](https://doi.org/10.3390/universe12090281) | 已发表 / published（*Universe* **2026**, 12(9), 281；2026-09-16） |

- arXiv：[JW-FD_V2: A 15-Year Multimodal Dataset for Solar Flare Forecasting](https://arxiv.org/abs/2608.19195)
- SPIE：[An end-to-end pipeline for multimodal solar flare forecasting dataset construction](https://www.spiedigitallibrary.org/conference-proceedings-of-spie/14155/3102831/An-end-to-end-pipeline-for-multimodal-solar-flare-forecasting/10.1117/12.3102831.full)
- *Universe*：[JW-FD: A 15-Year Multimodal Dataset for Solar Flare Forecasting](https://www.mdpi.com/2218-1997/12/9/281)

## 引用 / Citation

使用本仓库或 JW-FD 数据时，请引用期刊论文；流水线方法亦可引用 SPIE 会议文。完整 15 年数据请同时引用 ScienceDB v2：https://doi.org/10.57760/sciencedb.019mg

If you use this repository or the JW-FD data, please cite the journal article. The construction method can also be cited via the SPIE paper. For the full 15-year release, also cite ScienceDB v2.

```bibtex
@misc{Shao2026jwfdv2arxiv,
  author        = {Shao, Mingfu and Lin, Jiaben and Wang, Hui and Tong, Liyue and Yang, Chen and Zhang, Yin and Li, Yuyang},
  title         = {{JW-FD\_V2}: A 15-Year Multimodal Dataset for Solar Flare Forecasting},
  year          = {2026},
  eprint        = {2608.19195},
  archivePrefix = {arXiv},
  primaryClass  = {astro-ph.SR},
  url           = {https://arxiv.org/abs/2608.19195}
}

@article{Shao2026jwfd,
  author  = {Shao, Mingfu and Lin, Jiaben and Wang, Hui and Tong, Liyue and Yang, Chen and Zhang, Yin and Li, Yuyang},
  title   = {{JW-FD}: A 15-Year Multimodal Dataset for Solar Flare Forecasting},
  journal = {Universe},
  year    = {2026},
  volume  = {12},
  number  = {9},
  pages   = {281},
  doi     = {10.3390/universe12090281},
  url     = {https://www.mdpi.com/2218-1997/12/9/281}
}

@inproceedings{Shao2026jwfdspie,
  author    = {Shao, Mingfu and Lin, Jiaben and Wang, Hui and Tong, Liyue and Li, Yuyang},
  title     = {An end-to-end pipeline for multimodal solar flare forecasting dataset construction},
  booktitle = {Software and Cyberinfrastructure for Astronomy IX},
  series    = {Proc. SPIE},
  volume    = {14155},
  pages     = {94},
  year      = {2026},
  doi       = {10.1117/12.3102831},
  url       = {https://doi.org/10.1117/12.3102831}
}
```

- arXiv（JW-FD_V2）：https://arxiv.org/abs/2608.19195
- *Universe*：https://doi.org/10.3390/universe12090281
- SPIE：https://doi.org/10.1117/12.3102831
- 代码 / Code：https://github.com/Xiaoxuan-1/JW-FD
- 数据 / Data（Zenodo v1，约 10% 子集 / ~10% subset）：https://doi.org/10.5281/zenodo.21672850
- 数据 / Data（ScienceDB v2，完整 15 年 / full 15 years）：https://doi.org/10.57760/sciencedb.019mg
