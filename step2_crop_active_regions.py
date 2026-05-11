# -*- coding: utf-8 -*-
"""
步骤2: 从HMI磁图中裁剪活动区域（支持多年份+多月份数据）
输入: 多年份FITS文件 + 多年份SRS报告
输出: 裁剪后的FITS文件 (600x600像素)
"""

import glob
import gc
import os
import re
import numpy as np
import sunpy.map
from sunpy.coordinates import frames
import astropy.units as u
from astropy.coordinates import SkyCoord
import astropy.io.fits as fits
from scipy.ndimage import center_of_mass
from tqdm import tqdm
from multiprocessing import Pool, cpu_count

from config import PARAMS, get_path, get_srs_folders, get_all_fits_files
from utils import setup_logging, ensure_directory

# ========== 核心配置 ==========
SEARCH_SIZE = PARAMS.get('centroid_search_size', 80)
CALC_THRESHOLD = PARAMS.get('centroid_threshold', 100)
MAX_LON = PARAMS.get('max_longitude', 60)

def extract_time_from_fits_filename(filename):
    """从文件名提取时间字符串 YYYY-MM-DDTHH:MM:SS"""
    base = os.path.basename(filename)
    match = re.search(r'(\d{8})_(\d{6})', base)
    if match:
        d, t = match.group(1), match.group(2)
        return f"{d[:4]}-{d[4:6]}-{d[6:8]}T{t[:2]}:{t[2:4]}:{t[4:]}"
    return None

def parse_location_corrected(loc_str):
    """解析SRS位置，E为负，W为正"""
    if not isinstance(loc_str, str) or len(loc_str) < 6:
        return None, None
    try:
        lat_dir, lat_val = loc_str[0], float(loc_str[1:3])
        lon_dir, lon_val = loc_str[3], float(loc_str[4:])
        lat = lat_val if lat_dir == 'N' else -lat_val
        lon = -lon_val if lon_dir == 'E' else lon_val
        return lat, lon
    except:
        return None, None

def build_ar_reference_coords_raw_multi_year():
    """
    从多年份SRS报告中读取活动区坐标
    返回: (ar_raw_data, date_to_ars)
    """
    ar_raw_data = {}
    date_to_ars = {}
    
    srs_folders = get_srs_folders()
    
    for year, srs_folder in srs_folders:
        srs_files = sorted(glob.glob(os.path.join(srs_folder, '*.txt')))
        
        for srs_file in srs_files:
            base = os.path.basename(srs_file)
            match = re.search(r'(\d{8})', base)
            if not match:
                continue
            srs_date = match.group(1)
            
            data = []
            with open(srs_file, 'r') as f:
                lines = f.readlines()
            
            is_data = False
            for line in lines:
                if "Nmbr" in line and "Location" in line:
                    is_data = True
                    continue
                if is_data:
                    if line.strip() == "" or "IA" in line or "II" in line:
                        break
                    parts = line.split()
                    if len(parts) >= 2:
                        data.append(parts)
            
            today_ars = []
            for row in data:
                try:
                    nmbr, loc_str = row[0], row[1]
                    lat, lon = parse_location_corrected(loc_str)
                    if lat is None:
                        continue
                    
                    today_ars.append(nmbr)
                    if nmbr not in ar_raw_data:
                        ar_raw_data[nmbr] = {
                            'lat': lat,
                            'lon': lon,
                            'first_date': srs_date
                        }
                except:
                    continue
            
            date_to_ars[srs_date] = today_ars
    
    return ar_raw_data, date_to_ars

def build_fits_index_multi_year(fits_files):
    """
    建立FITS文件索引（按日期分组）
    """
    fits_by_date = {}
    
    for f in fits_files:
        t_str = extract_time_from_fits_filename(f)
        if t_str:
            date_key = t_str[:10].replace("-", "")  # 20240101
            if date_key not in fits_by_date:
                fits_by_date[date_key] = []
            fits_by_date[date_key].append(f)
    
    return fits_by_date

def get_centroid_fast(fits_path, rough_lon, rough_lat):
    """计算精确重心"""
    try:
        m = sunpy.map.Map(fits_path, memmap=True)
        p_rough = SkyCoord(
            lon=rough_lon*u.deg, lat=rough_lat*u.deg,
            frame=frames.HeliographicCarrington(obstime=m.date, observer='earth')
        )
        pix = m.world_to_pixel(p_rough)
        cx, cy = int(pix.x.value), int(pix.y.value)
        
        y0, y1 = max(0, cy - SEARCH_SIZE), min(4096, cy + SEARCH_SIZE)
        x0, x1 = max(0, cx - SEARCH_SIZE), min(4096, cx + SEARCH_SIZE)
        
        sub = np.nan_to_num(m.data[y0:y1, x0:x1])
        mask = np.abs(sub) > CALC_THRESHOLD
        
        if np.sum(mask) == 0:
            return p_rough
        
        dy, dx = center_of_mass(np.abs(sub) * mask)
        new_y, new_x = y0 + dy, x0 + dx
        
        dist = np.sqrt((new_x - cx)**2 + (new_y - cy)**2)
        if dist > 150:
            return p_rough
        
        return m.pixel_to_world(new_x*u.pix, new_y*u.pix).transform_to(
            frames.HeliographicCarrington(obstime=m.date, observer='earth')
        )
    except:
        return None

def process_single_ar_anchor(args):
    """处理单个活动区的锚点计算"""
    ar_num, info, date_to_ars, fits_by_date = args
    
    relevant_dates = sorted([d for d, ars in date_to_ars.items() if ar_num in ars])
    relevant_fits = []
    for d in relevant_dates:
        if d in fits_by_date:
            relevant_fits.extend(fits_by_date[d])
    relevant_fits.sort()
    
    if not relevant_fits:
        return ar_num, None
    
    try:
        m0 = sunpy.map.Map(relevant_fits[0], memmap=True)
        p_stony = SkyCoord(
            lon=info['lon']*u.deg, lat=info['lat']*u.deg,
            frame=frames.HeliographicStonyhurst(obstime=m0.date)
        )
        p_carr = p_stony.transform_to(
            frames.HeliographicCarrington(obstime=m0.date, observer='earth')
        )
        carr_lon, carr_lat = p_carr.lon.deg, p_carr.lat.deg
    except:
        return ar_num, None
    
    min_lon, best_frame = 999, None
    stride = max(1, len(relevant_fits) // 20)
    
    for f in relevant_fits[::stride]:
        try:
            m = sunpy.map.Map(f, memmap=True)
            pc = SkyCoord(
                lon=carr_lon*u.deg, lat=carr_lat*u.deg,
                frame=frames.HeliographicCarrington(obstime=m.date, observer='earth')
            )
            cur_lon = pc.transform_to(
                frames.HeliographicStonyhurst(obstime=m.date)
            ).lon.deg
            
            if abs(cur_lon) < min_lon:
                min_lon, best_frame = abs(cur_lon), f
            if min_lon < 5:
                break
        except:
            continue
    
    if not best_frame:
        best_frame = relevant_fits[len(relevant_fits)//2]
    
    centroid = get_centroid_fast(best_frame, carr_lon, carr_lat)
    
    result = {
        'carr_lon': float(centroid.lon.deg) if centroid else carr_lon,
        'carr_lat': float(centroid.lat.deg) if centroid else carr_lat,
    }
    
    return ar_num, result

def calculate_accurate_anchors(ar_raw_data, date_to_ars, fits_by_date):
    """计算活动区精确锚点（多进程优化版）"""
    print("正在计算活动区精确锚点...")
    
    tasks = [(ar_num, info, date_to_ars, fits_by_date)
             for ar_num, info in ar_raw_data.items()]
    
    optimized_ar_data = {}
    
    if PARAMS['use_multiprocess'] and len(tasks) > 1:
        max_workers = min(PARAMS['max_workers'], len(tasks))
        print(f"使用 {max_workers} 个进程并行计算...")
        
        with Pool(max_workers) as pool:
            results = list(tqdm(
                pool.imap_unordered(process_single_ar_anchor, tasks),
                total=len(tasks),
                desc="校正坐标"
            ))
        
        for ar_num, result in results:
            if result is not None:
                optimized_ar_data[ar_num] = result
    else:
        for ar_num, info in tqdm(ar_raw_data.items(), desc="校正坐标"):
            _, result = process_single_ar_anchor((ar_num, info, date_to_ars, fits_by_date))
            if result is not None:
                optimized_ar_data[ar_num] = result
    
    return optimized_ar_data

# 全局变量
_global_ar_data = None
_global_date_to_ars = None
_global_params = None

def init_worker(ar_data, date_to_ars, params):
    global _global_ar_data, _global_date_to_ars, _global_params
    _global_ar_data = ar_data
    _global_date_to_ars = date_to_ars
    _global_params = params

def process_fits_batch(args_batch):
    """处理一批FITS文件"""
    global _global_ar_data, _global_date_to_ars, _global_params
    ar_data = _global_ar_data
    date_to_ars = _global_date_to_ars
    crop_size = _global_params['crop_size']
    noaa_root_path = _global_params['noaa_path']
    
    total_processed = 0
    cropped_ars = set()
    
    for fits_path in args_batch:
        fits_time_str = extract_time_from_fits_filename(fits_path)
        if not fits_time_str:
            continue
        
        fits_date_key = fits_time_str[:10].replace("-", "")
        target_ars = date_to_ars.get(fits_date_key, [])
        
        if not target_ars:
            continue
        
        try:
            hmi_map = sunpy.map.Map(fits_path, memmap=True)
            carr_frame = frames.HeliographicCarrington(obstime=hmi_map.date, observer='earth')
            stony_frame = frames.HeliographicStonyhurst(obstime=hmi_map.date)
            
            for ar_num in target_ars:
                ar_info = ar_data.get(ar_num)
                if not ar_info:
                    continue
                
                carr_lon = ar_info['carr_lon']
                carr_lat = ar_info['carr_lat']
                target_coord = SkyCoord(lon=carr_lon*u.deg, lat=carr_lat*u.deg, frame=carr_frame)
                
                stony_pos = target_coord.transform_to(stony_frame)
                if abs(stony_pos.lon.deg) > MAX_LON:
                    continue
                
                pix_pos = hmi_map.world_to_pixel(target_coord)
                x = int(round(pix_pos.x.value))
                y = int(round(pix_pos.y.value))
                
                if not (crop_size <= x <= 4096-crop_size and crop_size <= y <= 4096-crop_size):
                    continue
                
                y1, y2 = y - crop_size, y + crop_size
                x1, x2 = x - crop_size, x + crop_size
                
                crop_data = hmi_map.data[y1:y2, x1:x2].copy()
                
                region_folder = os.path.join(noaa_root_path, ar_num)
                os.makedirs(region_folder, exist_ok=True)
                
                safe_time_str = fits_time_str.replace(":", "").replace("-", "").replace("T", "_")
                save_path = os.path.join(region_folder, f"AR{ar_num}_{safe_time_str}.fits")
                
                fits.writeto(save_path, crop_data, overwrite=True)
                total_processed += 1
                cropped_ars.add(ar_num)
        except:
            continue
    
    return total_processed, cropped_ars

def crop_active_regions():
    """主函数"""
    logger = setup_logging('step2_crop_regions')
    logger.info("="*60)
    logger.info("步骤2: 裁剪活动区域（多年份数据）- 开始")
    logger.info("="*60)
    
    noaa_path = get_path('fits_600')
    ensure_directory(noaa_path)
    
    # 读取多年份SRS报告
    print("读取多年份SRS报告...")
    ar_raw_data, date_to_ars = build_ar_reference_coords_raw_multi_year()
    print(f"找到 {len(ar_raw_data)} 个活动区")
    logger.info(f"找到 {len(ar_raw_data)} 个活动区")
    
    # 获取所有FITS文件
    print("扫描多年份FITS文件...")
    fits_files = get_all_fits_files()
    print(f"找到 {len(fits_files)} 个FITS文件")
    logger.info(f"找到 {len(fits_files)} 个FITS文件")
    
    if not fits_files:
        logger.warning("未找到FITS文件")
        return
    
    # 建立FITS索引
    fits_by_date = build_fits_index_multi_year(fits_files)
    
    # 计算精确锚点
    ar_optimized_data = calculate_accurate_anchors(ar_raw_data, date_to_ars, fits_by_date)
    
    # 准备多进程参数
    global_params = {
        'crop_size': PARAMS['crop_size'],
        'noaa_path': noaa_path,
    }
    
    batch_size = PARAMS.get('preload_count', 20)
    batches = [fits_files[i:i + batch_size] for i in range(0, len(fits_files), batch_size)]
    
    max_workers = PARAMS.get('max_workers', 12)
    print(f"\n开始并行处理 (进程数={max_workers})...")
    logger.info(f"开始并行处理 (进程数={max_workers})")
    
    total_processed = 0
    all_cropped_ars = set()
    
    with Pool(max_workers, initializer=init_worker, initargs=(ar_optimized_data, date_to_ars, global_params)) as pool:
        results = list(tqdm(
            pool.imap_unordered(process_fits_batch, batches),
            total=len(batches),
            desc="裁剪进度"
        ))
        for count, cropped_set in results:
            total_processed += count
            all_cropped_ars.update(cropped_set)
    
    print(f"\n步骤2完成: 共裁剪 {total_processed} 个文件")
    print(f"  - 成功裁剪的活动区数量: {len(all_cropped_ars)}")
    logger.info(f"步骤2完成: 共裁剪 {total_processed} 个文件")
    logger.info(f"成功裁剪的活动区数量: {len(all_cropped_ars)}")

if __name__ == "__main__":
    crop_active_regions()
