# -*- coding: utf-8 -*-
"""
工具函数模块 - 通用的辅助函数
"""

import os
import re
import logging
import numpy as np
from datetime import datetime, timedelta
from config import PATHS, PARAMS, get_path

def setup_logging(log_name):
    """设置日志配置"""
    log_file = os.path.join(get_path('log_folder'), f"{log_name}.log")
    
    # 获取logger
    logger = logging.getLogger(log_name)
    
    # 如果logger已经有handlers，说明已经配置过，直接返回
    if logger.handlers:
        return logger
    
    # 设置日志级别
    logger.setLevel(logging.INFO)
    
    # 禁止传播到父logger（避免重复）
    logger.propagate = False
    
    # 创建文件handler（使用'w'模式覆盖写入）
    file_handler = logging.FileHandler(log_file, mode='w', encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    
    # 创建formatter
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    
    # 添加handler到logger
    logger.addHandler(file_handler)
    
    return logger

def extract_date_from_filename(file_path):
    """从文件路径中提取日期，如 '20240101'"""
    match = re.search(r'(\d{8})', file_path)
    if match:
        return match.group(1)
    else:
        raise ValueError(f"未找到有效日期格式: {file_path}")

def extract_time_from_fits_filename(fits_filename):
    """从FITS文件名中提取时间部分，如 '20240101_000000'
    支持格式: hmi.M_720s.20240101_000000_TAI.3.magnetogram.fits
    """
    match = re.search(r'(\d{8}_\d{6})', fits_filename)
    if match:
        return match.group(1)
    else:
        return None


def extract_year_from_filename(path):
    """从形如 ARxxxx_YYYYMMDD_HHMMSS.ext 的路径中解析 4 位年份。失败返回 None。"""
    m = re.search(r'_(\d{4})\d{4}_\d{6}', os.path.basename(path))
    return int(m.group(1)) if m else None


def filter_location(location):
    """筛选位置 - 检查经纬度是否在±60度范围内"""
    match = re.match(r"([+-]\d{2})([+-]\d{2})", location)
    if match:
        lat, lon = int(match.group(1)), int(match.group(2))
        if abs(lat) <= 60 and abs(lon) <= 60:
            return True
    return False

def filter_location_single(location):
    """筛选单个位置坐标"""
    match_follow = re.match(r"([+-]?\d{2}\.\d{2})([+-]?\d{2}\.\d{2})", location)
    if match_follow:
        lat, lon = float(match_follow.group(1)), float(match_follow.group(2))
        if abs(lat) <= 60 and abs(lon) <= 60:
            return location
    return None

def parse_location(location_str):
    """解析位置字符串，转换方向标识为符号
    
    日心坐标系 (Stonyhurst):
    - N (北纬) = 正纬度
    - S (南纬) = 负纬度  
    - E (东经) = 负经度 (太阳东边，从地球看在左侧)
    - W (西经) = 正经度 (太阳西边，从地球看在右侧)
    """
    direction_map = {'S': '-', 'N': '+', 'E': '-', 'W': '+'}
    location = location_str.strip()
    for key, value in direction_map.items():
        location = location.replace(key, value)
    return location

def clean_value(value):
    """清理并处理特征值字符串"""
    value = value.replace('<', '').replace('>', '')
    value = re.sub(r'(?<=\d)\s(?=\d)', '', value)
    value = re.sub(r'(?<=\d)\s(?=\.)', '', value)
    value = re.sub(r'(?<=\.)\s(?=\d)', '', value)
    value = re.sub(r'-\s', '-', value)
    return value

def compare_labels(label1, label2):
    """比较耀斑标签等级"""
    order = {'X': 3, 'M': 2, 'C': 1, '0': 0}
    level1 = label1[0]
    level2 = label2[0]
    if order[level1] != order[level2]:
        return order[level1] > order[level2]
    else:
        # 同一级别，比较数字部分
        num1 = float(label1[1:])
        num2 = float(label2[1:])
        return num1 > num2

def label_meets_threshold(best_label, threshold):
    """best_label 是否达到阈值（>=）。best_label 为 '0' 直接返回 '0'。"""
    if best_label == '0':
        return '0'
    if best_label == threshold or compare_labels(best_label, threshold):
        return '1'
    return '0'

def hmi_norm(image_file, threshold=None):
    """HMI磁图归一化处理
    
    Args:
        image_file: 输入图像数组
        threshold: 磁场阈值，默认使用配置文件中的值 (200/500/1000)
    """
    if threshold is None:
        threshold = PARAMS['mag_threshold']
    
    # 处理NaN值
    image_file[np.isnan(image_file)] = -threshold
    # 设置阈值
    arr1 = (image_file > threshold)
    image_file[arr1] = threshold
    arr0 = (image_file < -threshold)
    image_file[arr0] = -threshold
    
    # 获取最小值和最大值
    min_val, max_val = np.min(image_file), np.max(image_file)
    hmi_mag = (image_file - min_val) / (max_val - min_val) * 255
    return hmi_mag.astype('uint8')

def ensure_directory(path):
    """确保目录存在（多进程安全）"""
    os.makedirs(path, exist_ok=True)