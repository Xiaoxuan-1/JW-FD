# JW-FD

[中文](README.md) | **English**

This repository builds a multi-threshold, multi-horizon solar-flare dataset from **HMI magnetograms** and **NOAA SRS / Events**. It crops active regions from full-disk FITS, extracts magnetic features, and joins them to the flare catalog (CSV, with optional PNG and movies).

Open-source construction pipeline for the paper: <https://github.com/Xiaoxuan-1/JW-FD>.

Paper: [JW-FD_V2: A 15-Year Multimodal Dataset for Solar Flare Forecasting](https://arxiv.org/abs/2608.19195) (arXiv:2608.19195)

## Data release

| Version | Contents | Access |
|------|------|----------|
| Zenodo **v1** | ~10% representative subset | [doi:10.5281/zenodo.21672850](https://doi.org/10.5281/zenodo.21672850) · [record](https://zenodo.org/records/21672850) |
| ScienceDB **v2** | full 15 years | [doi:10.57760/sciencedb.019mg](https://doi.org/10.57760/sciencedb.019mg) |

Coverage is **2011-01-01 through 2025-12-31**. The default PNG working point is **800 G**, with ten saturation thresholds from **200 to 2000 G in steps of 200 G**. The official split is an active-region-level 8:1:1 partition with seed 3970. The frozen membership list is [`split_v2_ar_membership.json`](split_v2_ar_membership.json).

Reassemble the Zenodo v1 split archive:

```bash
cat JW-FD_subset_10pct.tar.zst.*.part > JW-FD_subset_10pct.tar.zst
zstd -t JW-FD_subset_10pct.tar.zst
tar -I zstd -xf JW-FD_subset_10pct.tar.zst
```

## Pipeline

| Step | Script | Description |
|------|------|------|
| 1 | `step1_extract_flare_labels.py` | Extract XRA flare records from NOAA Events into `flare_labels.csv` (begin, max, end, and class) |
| 2 | `step2_crop_active_regions.py` | Crop **600×600** patches from full-disk HMI FITS at the SRS location into unrotated `fits_600_raw`. The seed frame is the one closest to disk center |
| 2b | `step2b_rotate_fits.py` | Rotate `fits_600_raw` by 180° into `fits_600`. Full-disk HMI is stored rotated; cropping does not change orientation |
| 3 | `step3_convert_to_png.py` | PNG from the rotated FITS: a vertical flip, then a fixed ±B_th scale (NaN→0 G, 0 G→gray 127) |
| 4 | `step4_generate_dataset_fits.py` | **29** features and labels from FITS → `solar_flare_dataset_fits_{suffix}.csv` |
| 5 | `step5_generate_dataset_png.py` | Features and labels from PNG → `solar_flare_dataset_png_{suffix}.csv` |
| 6 | `step6_make_movie.py` | Evolution movies from each region's PNG sequence (`movies_600_Th{mag_threshold}`) |

Entry points:

- **Non-interactive, suitable for `nohup`:** `python run_pipeline.py [start] [end]`
- **Interactive menu:** `python main_pipeline.py`
- **All ten thresholds:** `python batch_update_thresholds.py` (default ten thresholds, then the seed-3970 membership split)

## Environment

```bash
conda env create -f environment.yml
conda activate JW-FD
```

Temporary files go to `TMPDIR`, or to `/tmp` when that variable is unset.

## Configuration ([`config.py`](config.py))

Set these to the paths on your machine before running.

| Key | Meaning |
|----|------|
| `DATA_ROOT` | Raw-data root, with `Labels` and `Fits` underneath |
| `OUTPUT_PATH` | Intermediate products, CSV, labels, and logs |
| `START_YEAR` / `END_YEAR` | Default **2011–2025**. Steps 3–6 filter on the `YYYYMMDD` in each filename |
| `PARAMS['mag_threshold']` | Default PNG working point, **800 G** |
| `PARAMS['png_thresholds']` | Ten thresholds: `200, 400, …, 2000` |
| `SPLIT_SEED` | Official split seed, **3970** |
| `PARAMS['prediction_hours']` | Forecast horizons in hours, one `int` or a `list[int]`, one label column per horizon |
| `PARAMS['max_latitude']` / `PARAMS['max_longitude']` | Disk-position cuts in Step 2 |
| `FLARE_LABEL_THRESHOLDS` | Binary label thresholds, default `C1.0, M1.0, M5.0, X1.0` |

PNG scaling: `NaN → 0 G`, `clip(B, -B_th, B_th)`, then `(B + B_th) / (2 B_th) * 255` as `uint8` (0 G maps to gray 127).

The filename suffix comes from `get_output_suffix()`: `Lat{lat}_Lon{lon}_Th{threshold}`.

### Raw data layout (`Labels`)

- **SRS:** `{labels_root}/{year}/{year}_SRS` or `{labels_root}/{year}_SRS`
- **Events:** `{labels_root}/{year}/{year}_events` or `{labels_root}/{year}_events`

### HMI FITS (`Fits`)

`get_fits_folders()` scans the year/month subdirectories. Those paths must match `config`.

## Dataset CSV

- **Features:** 29 columns, named in `FEATURE_NAMES` ([`config.py`](config.py)).
- **Labels:** for each horizon `hr` and each threshold, `flare_label_{thr}_{hr}hr`; each horizon also has `flare_class_{hr}hr` (the strongest class in that window).
- **Metadata:** `image_filename`, `image_path`.

The FITS and PNG CSV files differ only in the image source. Their columns match (`solar_flare_dataset_fits_*` / `solar_flare_dataset_png_*`).

A frame is positive under `get_flare_label` in Steps 4 and 5 when the flare begins inside the half-open interval `[Begin_Time - hr, Begin_Time)`. The start time itself, and everything after it, is not a positive for that horizon.

Split:

```bash
python split_dataset.py --input /path/to/solar_flare_dataset_png_Lat60_Lon60_Th800.csv
# default: split_v2_ar_membership.json (seed 3970)
```

## Commands

```bash
# full pipeline
python run_pipeline.py

# steps 1–3 only
python run_pipeline.py 1 3

# step 4 only
python run_pipeline.py 4 4

# ten PNG thresholds and their CSV files (200–2000 G)
python batch_update_thresholds.py

# background
nohup python run_pipeline.py 4 5 > pipeline_step45.log 2>&1 &
```

## What is in this repository

- This repository holds the **code** and the official AR membership list. The bulk data and logs are not versioned (see [`.gitignore`](.gitignore)).
- The subset is listed under Data release. The full 15-year release is ScienceDB v2: https://doi.org/10.57760/sciencedb.019mg

## Papers

| Paper | Link | Status |
|------|------|------|
| Latest preprint | [JW-FD_V2: A 15-Year Multimodal Dataset for Solar Flare Forecasting](https://arxiv.org/abs/2608.19195) | arXiv:2608.19195 |
| SPIE Proceedings (ATI 2026, 14155-94) | [doi:10.1117/12.3102831](https://doi.org/10.1117/12.3102831) | Published (Proc. SPIE **14155**, 2026-08-19) |
| MDPI *Universe* | [doi:10.3390/universe12090281](https://doi.org/10.3390/universe12090281) | Published (*Universe* **2026**, 12(9), 281; 2026-09-16) |

- arXiv: [JW-FD_V2: A 15-Year Multimodal Dataset for Solar Flare Forecasting](https://arxiv.org/abs/2608.19195)
- SPIE: [An end-to-end pipeline for multimodal solar flare forecasting dataset construction](https://www.spiedigitallibrary.org/conference-proceedings-of-spie/14155/3102831/An-end-to-end-pipeline-for-multimodal-solar-flare-forecasting/10.1117/12.3102831.full)
- *Universe*: [JW-FD: A 15-Year Multimodal Dataset for Solar Flare Forecasting](https://www.mdpi.com/2218-1997/12/9/281)

## Citation

If you use this repository or the JW-FD data, please cite the journal article. The construction method can also be cited via the SPIE paper. For the full 15-year release, also cite ScienceDB v2: https://doi.org/10.57760/sciencedb.019mg

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

- arXiv (JW-FD_V2): https://arxiv.org/abs/2608.19195
- *Universe*: https://doi.org/10.3390/universe12090281
- SPIE: https://doi.org/10.1117/12.3102831
- Code: https://github.com/Xiaoxuan-1/JW-FD
- Data (Zenodo v1, ~10% subset): https://doi.org/10.5281/zenodo.21672850
- Data (ScienceDB v2, full 15 years): https://doi.org/10.57760/sciencedb.019mg
