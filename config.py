# -*- coding: utf-8 -*-
"""
配置文件 - 统一管理所有路径和参数（支持多年份数据）

本文件与 /data/Datasets/JW-FD-fixed/code/config.py 保持同一套路径和参数。
产出写入 OUTPUT_PATH。SOURCE_PATH 是已发布的旧数据，只读。
"""

import os
import glob
import re

# 基础路径配置
OUTPUT_PATH = "/data/Datasets/JW-FD-fixed"   # 现行产出（FITS / PNG / CSV / 视频 / 日志）
SOURCE_PATH = "/data/Datasets/JW-FD"         # 已发布旧数据，只读，不要写入

# 数据年份范围配置
START_YEAR = 2011
END_YEAR = 2025


def year_in_range(year):
    """检查年份是否在 [START_YEAR, END_YEAR] 闭区间内。None 视为不在范围。"""
    if year is None:
        return False
    return START_YEAR <= year <= END_YEAR


# 数据路径配置（支持多年份）
DATA_ROOT = "/data/Datasets"

PATHS = {
    # 原始数据根目录
    'data_root': DATA_ROOT,
    'labels_root': f"{DATA_ROOT}/Labels",
    'fits_root': f"{DATA_ROOT}/Fits",

    # step2 写出未旋转裁剪；step2b 再 rot180 到 fits_600
    'fits_600_raw': lambda: f"{OUTPUT_PATH}/fits_600_raw",
    'fits_600_source': lambda: f"{SOURCE_PATH}/fits_600",
    'fits_600': lambda: f"{OUTPUT_PATH}/fits_600",
    'flare_labels': f"{OUTPUT_PATH}/flare_labels.csv",

    'png_600': lambda: get_png_dir(PARAMS['mag_threshold']),
    'movies': lambda: f"{OUTPUT_PATH}/movies_600_Th{PARAMS['mag_threshold']}",
    'dataset': lambda: f"{OUTPUT_PATH}/solar_flare_dataset_{get_output_suffix()}.csv",

    'log_folder': f"{OUTPUT_PATH}/logs"
}


def get_png_dir(threshold=None):
    """某个磁场阈值对应的 PNG 输出根目录。"""
    if threshold is None:
        threshold = PARAMS['mag_threshold']
    return f"{OUTPUT_PATH}/png_600_Th{threshold}"


def get_path(key):
    """获取路径，支持动态路径"""
    path = PATHS[key]
    return path() if callable(path) else path

def get_srs_folders():
    """
    获取所有年份的SRS文件夹路径
    返回: [(year, folder_path), ...]
    """
    srs_folders = []
    labels_root = get_path('labels_root')

    for year in range(START_YEAR, END_YEAR + 1):
        patterns = [
            f"{labels_root}/{year}/{year}_SRS",
            f"{labels_root}/{year}_SRS"
        ]

        for pattern in patterns:
            if os.path.exists(pattern):
                srs_folders.append((year, pattern))
                break

    return srs_folders

def get_events_folders():
    """
    获取所有年份的Events文件夹路径
    返回: [(year, folder_path), ...]
    """
    events_folders = []
    labels_root = get_path('labels_root')

    for year in range(START_YEAR, END_YEAR + 1):
        patterns = [
            f"{labels_root}/{year}/{year}_events",
            f"{labels_root}/{year}_events"
        ]

        for pattern in patterns:
            if os.path.exists(pattern):
                events_folders.append((year, pattern))
                break

    return events_folders

def get_fits_folders():
    """
    获取所有年份+月份的FITS文件夹路径
    返回: [(year, month, folder_path), ...]
    """
    fits_folders = []
    fits_root = get_path('fits_root')

    for year in range(START_YEAR, END_YEAR + 1):
        year_patterns = [
            f"{fits_root}/HMI/{year}_with_headers"
        ]

        year_folder = None
        for pattern in year_patterns:
            if os.path.exists(pattern):
                year_folder = pattern
                break

        if not year_folder:
            continue

        for month in range(1, 13):
            month_str = f"{month:02d}"
            month_folder = os.path.join(year_folder, month_str)

            if os.path.exists(month_folder):
                fits_folders.append((year, month, month_folder))

    return fits_folders

def get_all_fits_files():
    """
    获取所有FITS文件的完整路径列表。

    同时收录以点开头的 ``.*fits``。2011 年 9 月的 HMI 磁图全部是这种文件名，
    ``glob("*.fits")`` 看不到。同一时刻若既有可见文件又有点文件，保留可见文件。
    返回: [fits_file_path, ...]
    """
    by_time = {}
    fits_folders = get_fits_folders()

    for year, month, folder_path in fits_folders:
        names = glob.glob(os.path.join(folder_path, "*.fits"))
        names.extend(glob.glob(os.path.join(folder_path, ".*.fits")))
        for path in names:
            base = os.path.basename(path)
            match = re.search(r'(\d{8}_\d{6})', base)
            key = (folder_path, match.group(1) if match else base)
            previous = by_time.get(key)
            if previous is None or (
                os.path.basename(previous).startswith('.') and not base.startswith('.')
            ):
                by_time[key] = path

    return sorted(by_time.values())

# 处理参数
PARAMS = {
    'crop_size': 300,  # 裁剪半径 (600x600像素)
    'image_size': 4096,  # HMI图像尺寸

    'max_latitude': 60,
    'max_longitude': 60,

    # 论文默认工作点 800 G。Step3 一次生成 png_thresholds 全部十档。
    'mag_threshold': 800,
    'png_thresholds': [200, 400, 600, 800, 1000, 1200, 1400, 1600, 1800, 2000],

    # PNG 压缩级别。PIL 默认 6 是 Step3 的瓶颈。
    'png_compress_level': 1,

    'prediction_hours': [1, 3, 6, 12, 24, 48, 72],

    'use_multiprocess': True,
    'max_workers': 64,
    'preload_count': 100,

    'centroid_search_size': 80,    # 重心搜索半径 (像素)
    'centroid_threshold': 100,     # 重心计算磁场阈值 (Gauss)
}


# 官方划分：分层拒绝采样，seed=3970。成员名单见 split_v2_ar_membership.json。
SPLIT_SEED = 3970


def get_prediction_hours_list():
    """将 PARAMS['prediction_hours'] 归一化为升序、去重的 list[int]。"""
    raw = PARAMS['prediction_hours']
    if isinstance(raw, int):
        raw = [raw]
    return sorted({int(h) for h in raw})


def get_png_thresholds():
    """Step3 待生成的阈值列表（升序去重）。"""
    return sorted({int(t) for t in PARAMS['png_thresholds']})


def get_output_suffix():
    """根据参数生成输出文件后缀（多窗口时不再带单一时长后缀）"""
    lat = PARAMS['max_latitude']
    lon = PARAMS['max_longitude']
    threshold = PARAMS['mag_threshold']
    return f"Lat{lat}_Lon{lon}_Th{threshold}"


def get_output_suffix_fits():
    """FITS 版数据集后缀：不带 Th。特征在高斯值上计算，与 mag_threshold 无关。"""
    lat = PARAMS['max_latitude']
    lon = PARAMS['max_longitude']
    return f"Lat{lat}_Lon{lon}"

FEATURE_NAMES = [
    'Gradient mean', 'Gradient std', 'Gradient median', 'Gradient min', 'Gradient max',
    'Gradient skewness', 'Gradient kurtosis', 'NL length', 'NL no. fragments',
    'NL gradient-weighted length', 'NL curvature mean', 'NL curvature std',
    'NL curvature median', 'NL curvature min', 'NL curvature max',
    'NL bending energy mean', 'NL bending energy std', 'NL bending energy median',
    'NL bending energy min', 'NL bending energy max', 'Wavelet Energy L1',
    'Wavelet Energy L2', 'Wavelet Energy L3', 'Wavelet Energy L4', 'Wavelet Energy L5',
    'Total positive flux', 'Total negative flux', 'Total signed flux', 'Total unsigned flux'
]

FLARE_LABEL_THRESHOLDS = ['C1.0', 'M1.0', 'M5.0', 'X1.0']

def _ensure_log_folder():
    """确保日志目录存在"""
    log_folder = PATHS['log_folder']
    if callable(log_folder):
        log_folder = log_folder()
    os.makedirs(log_folder, exist_ok=True)

_ensure_log_folder()
