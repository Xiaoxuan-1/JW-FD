# JW-FD Pipeline PPT — English Content

Copy-paste ready text for the technical pipeline presentation. Source: repository code + *太阳耀斑预报数据集JW-FD：构建、应用与完整解析* PDF.

---

## INTRODUCTION (copy-paste block)

**Context.** Solar flares are among the most energetic manifestations of solar magnetic activity and a primary driver of space weather. Major flares (M/X-class) can disrupt satellite operations, aviation communications, and power-grid infrastructure. Forecasting flare occurrence **before eruption** from photospheric magnetograms remains a central challenge for solar physics and operational space-weather services.

**The gap.** Traditional flare datasets suffer from **short temporal coverage**, **single-modality releases** (images or parameters only), **rigid label systems**, a **risk of cross-split leakage** when samples from the same active region span train and test sets, and a **lack of standardized, extensible pipelines** for reproducible construction and extension.

**JW-FD.** **JW-FD** (JW Flare Dataset: a long-horizon flare forecasting dataset for multimodal large models) is a large-scale, multimodal benchmark built through a six-step automated pipeline. It links NOAA X-ray flare Events to **600×600** SDO/HMI line-of-sight magnetogram crops tracked per NOAA active region, and exports co-registered **FITS** and **PNG** sequences, a **66-dimensional** tabular record per snapshot (29 magnetic features + 35 flare-label fields + 2 metadata fields), and **2,687** per-AR **MP4** evolution videos.

**Dataset overview.**

| Item | Value |
|------|-------|
| Temporal coverage | 1 Jan 2011 – 31 Dec 2024 (14 years; Solar Cycles 24–25) |
| Active regions | 2,687 independent NOAA ARs |
| Effective samples | 1,750,184 image snapshots (~1.75M) |
| Formats | FITS, PNG, CSV, MP4 |
| Standard split | 8:1:1 (train / validation / test) by **active region** — no cross-split AR leakage |
| Data sources | SDO/HMI full-disk LOS magnetograms; NOAA/USAF SRS; NOAA Events (XRA) |

**Label design.** For prediction horizons {1, 3, 6, 12, 24, 48, 72} hours and GOES thresholds {C1.0, M1.0, M5.0, X1.0}, binary labels are assigned only within the strict pre-eruption window **[Begin − hr, Begin)** — post-eruption frames are never positive.

---

## CONCLUSIONS (copy-paste block)

**Contributions.** JW-FD is the first large-scale, multimodal flare forecasting dataset that tightly binds **visual magnetograms / evolution videos**, **29 physics-based magnetic descriptors** (gradient, neutral-line, wavelet, and flux statistics), and **35 configurable flare-label dimensions** through a documented six-step pipeline. An **8:1:1 active-region split** eliminates temporal leakage and establishes a credible evaluation benchmark for classical ML, CNNs/ViTs, and multimodal large models.

**Validation insight.** Ablation on magnetogram-to-PNG saturation threshold shows that retaining strong-field boundary structure matters: at **B_th ≈ 1000 G**, visual models achieve the best ≥C1.0 flare forecasting performance reported in the dataset study (**TPR = 0.6320**, **TSS = 0.5225**), supporting physics-informed multimodal alignment.

**Impact.** JW-FD bridges solar physics and operational space-weather forecasting: it supports MLLM training benchmarks, algorithm comparison across horizons and flare classes, and downstream intelligent warning pipelines. The open, modular codebase ([GitHub](https://github.com/Xiaoxuan-1/JW-FD)) enables reproducible extension.

**Future work.** Integrate multi-wavelength channels (e.g., SDO/AIA EUV, continuum + magnetogram as in JW-SSD), explicit temporal dynamics beyond single-frame features, operational real-time ingestion APIs, and event-level vs. AR-level benchmark protocols.

---

## Flowchart English Translations

### Section headers

| Chinese | English |
|---------|---------|
| INTRODUCTION | INTRODUCTION |
| METHODS | METHODS |
| RESULTS | RESULTS / CONCLUSIONS |

### Data input

| Chinese | English |
|---------|---------|
| 数据输入 | Data Input |
| Events | Events |
| SRS | SRS (Solar Region Summary) |
| Magnetograms (Fits) | Magnetograms (FITS) |

### Pipeline processing

| Chinese | English |
|---------|---------|
| 流程处理 | Pipeline Processing |
| 步骤1: 提取耀斑标签 | Step 1: Extract Flare Labels |
| Events 文件解析 | Parse Events files |
| 耀斑爆发标签 | Flare eruption labels |
| 步骤2: 活动区裁剪&跟踪 | Step 2: Active Region Cropping & Tracking |
| SRS 文件解析 | Parse SRS files |
| FITS 文件遍历 | Traverse FITS files |
| 坐标转换 | Coordinate transformation |
| 最佳帧寻找 | Best-frame selection |
| 磁场重心校正 | Magnetic-field centroid correction |
| 精准卡林顿坐标 | Precise Carrington coordinates |
| 并行裁剪 | Parallel cropping |
| 经纬度过滤 | Latitude/longitude filtering |
| 边界检查 | Boundary check |
| 活动区完整生命周期 FITS (600×600) | Full-lifecycle active-region FITS (600×600) |
| 步骤3: FITS → PNG | Step 3: FITS → PNG |
| 步骤4: 数据集生成 (FITS格式) | Step 4: Dataset generation (FITS-based) |
| 步骤5: 数据集生成 (PNG格式) | Step 5: Dataset generation (PNG-based) |
| 步骤6: 活动区演化视频 (MP4) | Step 6: Active-region evolution videos (MP4) |
| 长周期耀斑预报数据集 | Long-horizon solar flare forecasting dataset |

### Dataset record construction (right panel)

| Chinese (original) | English |
|------------------|---------|
| 数据集构建 (33维向量) | **Dataset Record Construction (66-dimensional record)** |
| 标签匹配 | Label matching |
| 特征提取模块 (29维) | Feature extraction module (29 dimensions) |
| 耀斑标签信息 (35维) | Flare label information (35 dimensions) |
| 文件基本信息 (2维) | Basic file metadata (2 dimensions) |

> **PPT fix:** Replace “33-dimensional vector” with **66-dimensional record (29 + 35 + 2)** to match the PDF and current pipeline.

---

## 66-Dimensional Record Structure

Each CSV row = one magnetogram snapshot aligned to one AR at one UTC timestamp.

| Block | Dimensions | Content |
|-------|------------|---------|
| Feature extraction | **29** | Gradient stats (7), neutral-line geometry (13), wavelet energy (5), flux integrals (4) — see `FEATURE_NAMES` in `config.py` |
| Flare labels | **35** | 28 binary columns: 7 horizons × 4 thresholds (`flare_label_{C1.0,M1.0,M5.0,X1.0}_{1,3,6,12,24,48,72}hr`); 7 class strings: strongest GOES class per horizon (`flare_class_{hr}hr`) |
| File metadata | **2** | `image_filename`, `image_path` |

**Label semantics:** Positive binary labels only when image time *t* satisfies **Begin − hr ≤ t < Begin** (strict pre-eruption forecasting).

**Alignment keys:** AR number + timestamp jointly link FITS, PNG, CSV rows, and MP4 frame sequences.

---

## Step 2 Technical Notes (speaker notes / figure captions)

- **SRS parsing:** Extract NOAA AR number and heliographic location (e.g., N12W45); convert to Carrington coordinates on the solar rotation frame.
- **Best-frame selection:** Among each AR’s daily HMI sequence, pick the frame nearest central meridian (minimize |Stonyhurst longitude|) before centroid refinement — reduces projection distortion.
- **Centroid correction:** Within ±80 px of the rough anchor, mask pixels with |B| > 100 G and compute center of mass to refine the Carrington anchor.
- **Latitude/longitude filter:** Exclude ARs with |latitude| or |longitude| > 60° (config: `max_latitude`, `max_longitude`).
- **Boundary check:** Crop center must lie within the 4096×4096 disk so a full 600×600 sub-image is valid (300 px radius).
- **Output:** Per-AR folders of 600×600 LOS magnetogram FITS covering the full AR lifecycle.

## Step 3 Technical Notes (optional)

- **Orientation:** Left-right flip (`fliplr`) so display follows standard “north up, east left” convention.
- **PNG normalization:** Saturate at configurable **B_th** (e.g., 200–2000 G); map to [0, 255] grayscale. PDF reports **1000 G** as optimal for ≥C1.0 visual forecasting.

## Step 6 Technical Notes (optional)

- Input: time-sorted PNG sequence per AR (~12 min cadence).
- Output: MP4 at **60 FPS** showing magnetic evolution for video models.

---

## Suggested slide bullets (METHODS summary)

1. **Step 1** — Parse NOAA Events (XRA): AR number, Begin/Max/End times, GOES class → `flare_labels.csv`.
2. **Step 2** — SRS + full-disk HMI FITS → Carrington anchor, centroid correction, parallel 600×600 crop.
3. **Step 3** — FITS → thresholded, normalized PNG (600×600).
4. **Steps 4–5** — Extract 29 features + match 35 flare labels + 2 metadata fields → CSV (FITS or PNG branch).
5. **Step 6** — Per-AR PNG sequence → MP4 evolution video.
6. **Integration** — Label matching binds eruption labels to image timelines → multimodal JW-FD corpus.
