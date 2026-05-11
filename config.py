# -*- coding: utf-8 -*-
"""
配置文件 - 统一管理所有路径和参数（支持多年份数据）
"""

import os
import glob

# 基础路径配置
OUTPUT_PATH = f"/data/Datasets/JW-FD"

# 数据年份范围配置
START_YEAR = 2011
END_YEAR = 2025


def year_in_range(year):
    """检查年份是否在 [START_YEAR, END_YEAR] 闭区间内。None 视为不在范围。"""
    if year is None:
        return False
    return START_YEAR <= year <= END_YEAR


# 数据路径配置（支持多年份）
DATA_ROOT = "/data/Datasets"  # 根据实际情况修改

PATHS = {
    # 原始数据根目录
    'data_root': DATA_ROOT,
    'labels_root': f"{DATA_ROOT}/Labels",
    'fits_root': f"{DATA_ROOT}/Fits",
    
    # 处理后数据 (动态生成路径)
    'fits_600': lambda: f"{OUTPUT_PATH}/fits_600",
    'png_600': lambda: f"{OUTPUT_PATH}/png_600_Th{PARAMS['mag_threshold']}",
    # 与 png_600 同一套 Th 命名，避免不同 mag_threshold 共用同一视频目录
    'movies': lambda: f"{OUTPUT_PATH}/movies_600_Th{PARAMS['mag_threshold']}",
    
    # 输出文件
    'flare_labels': f"{OUTPUT_PATH}/flare_labels.csv",
    'dataset': lambda: f"{OUTPUT_PATH}/solar_flare_dataset_{get_output_suffix()}.csv",
    
    # 日志文件
    'log_folder': f"{OUTPUT_PATH}/logs"
}

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
        # 支持两种命名格式: 2011_SRS 或 2011/2011_SRS
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
        # 支持两种命名格式: 2011_events 或 2011/2011_events
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
        # 查找该年份的FITS根目录
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
        
        # 遍历该年份下的所有月份文件夹
        for month in range(1, 13):
            month_str = f"{month:02d}"
            month_folder = os.path.join(year_folder, month_str)
            
            if os.path.exists(month_folder):
                fits_folders.append((year, month, month_folder))
    
    return fits_folders

def get_all_fits_files():
    """
    获取所有FITS文件的完整路径列表
    返回: [fits_file_path, ...]
    """
    all_fits = []
    fits_folders = get_fits_folders()
    
    for year, month, folder_path in fits_folders:
        # 查找该文件夹下的所有FITS文件
        fits_files = glob.glob(os.path.join(folder_path, "*.fits"))
        all_fits.extend(fits_files)
    
    return sorted(all_fits)

# 处理参数
PARAMS = {
    # 图像裁剪参数
    'crop_size': 300,  # 裁剪半径 (600x600像素)
    'image_size': 4096,  # HMI图像尺寸
    
    # 位置筛选参数
    'max_latitude': 60,
    'max_longitude': 60,
    
    # 磁场归一化参数 (可选值: 200, 500, 1000)
    'mag_threshold': 200,  # 选择: 200 | 500 | 1000
    
    # 耀斑预测窗口（小时）；可为 int 或 list[int]，一次生成多窗口标签列
    'prediction_hours': [1, 3, 6, 12, 24, 48, 72],
    
    # 多进程参数
    'use_multiprocess': True,
    'max_workers': 64,  # 进程数
    'preload_count': 100,  # 每个进程预加载的FITS文件数量
    'cpu_usage_limit': 1.0,  # CPU使用率限制 (100%)
    
    # Step2 重心校正参数
    'centroid_search_size': 80,    # 重心搜索半径 (像素)
    'centroid_threshold': 100,     # 重心计算磁场阈值 (Gauss)
}


def get_prediction_hours_list():
    """将 PARAMS['prediction_hours'] 归一化为升序、去重的 list[int]。"""
    raw = PARAMS['prediction_hours']
    if isinstance(raw, int):
        raw = [raw]
    return sorted({int(h) for h in raw})


def get_output_suffix():
    """根据参数生成输出文件后缀（多窗口时不再带单一时长后缀）"""
    lat = PARAMS['max_latitude']
    lon = PARAMS['max_longitude']
    threshold = PARAMS['mag_threshold']
    return f"Lat{lat}_Lon{lon}_Th{threshold}"

# 特征名称
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

# Step4/5 同时输出的多阈值二分类列（顺序即 CSV 列顺序）
FLARE_LABEL_THRESHOLDS = ['C1.0', 'M1.0', 'M5.0', 'X1.0']

# 确保日志目录存在
def _ensure_log_folder():
    """确保日志目录存在"""
    log_folder = PATHS['log_folder']
    if callable(log_folder):
        log_folder = log_folder()
    os.makedirs(log_folder, exist_ok=True)

_ensure_log_folder()
