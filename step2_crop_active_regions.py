# -*- coding: utf-8 -*-
"""
步骤2: 从HMI磁图中裁剪活动区域（支持多年份+多月份数据）
输入: 多年份FITS文件 + 多年份SRS报告
输出: 裁剪后的FITS文件 (600x600像素)
"""

import glob
import gc
import math
import os
import re
import argparse
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
# 日面经度随时间的大致变化，用来在 SRS 当天里选最靠近日面中心的一帧。
SYNODIC_DEG_PER_DAY = 13.2

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
                    days = ar_raw_data.setdefault(nmbr, {'days': []})['days']
                    if not any(item['date'] == srs_date for item in days):
                        days.append({
                            'date': srs_date,
                            'lat': lat,
                            'lon': lon,
                        })
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

def hours_from_midnight(fits_path):
    """文件名时刻相对当天 00:00 的小时数。解析失败返回 None。"""
    t_str = extract_time_from_fits_filename(fits_path)
    if not t_str:
        return None
    hh, mm, ss = t_str[11:13], t_str[14:16], t_str[17:19]
    return int(hh) + int(mm) / 60.0 + int(ss) / 3600.0


def hours_to_central_meridian(lon_deg, lat_deg):
    """把 00:00 的日面经度外推到过日面中心的时刻（小时，可超出 0–24）。"""
    rate = SYNODIC_DEG_PER_DAY * math.cos(math.radians(lat_deg))
    if abs(rate) < 1e-6:
        return 0.0
    return -lon_deg / rate * 24.0


def process_single_ar_anchor(args):
    """处理单个活动区的锚点计算。

    种子是 SRS 里 |日面经度| 最小、且当天有磁图的那一天的位置。
    在这一天的磁图里取最接近日面中心的一帧，用该帧时刻换成卡林顿坐标，
    再做一次 ±80 像素重心。
    """
    ar_num, info, date_to_ars, fits_by_date = args

    days = sorted(info.get('days', []), key=lambda item: (abs(item['lon']), item['date']))
    chosen = None
    day_fits = None
    for day in days:
        found = sorted(fits_by_date.get(day['date'], []))
        if found:
            chosen = day
            day_fits = found
            break

    if chosen is None:
        return ar_num, None

    target_hours = hours_to_central_meridian(chosen['lon'], chosen['lat'])
    best_frame = None
    best_gap = None
    for fits_path in day_fits:
        hours = hours_from_midnight(fits_path)
        if hours is None:
            continue
        gap = abs(hours - target_hours)
        if best_gap is None or gap < best_gap:
            best_gap = gap
            best_frame = fits_path
    if best_frame is None:
        best_frame = day_fits[len(day_fits) // 2]

    try:
        m0 = sunpy.map.Map(best_frame, memmap=True)
        p_stony = SkyCoord(
            lon=chosen['lon']*u.deg, lat=chosen['lat']*u.deg,
            frame=frames.HeliographicStonyhurst(obstime=m0.date)
        )
        p_carr = p_stony.transform_to(
            frames.HeliographicCarrington(obstime=m0.date, observer='earth')
        )
        carr_lon, carr_lat = p_carr.lon.deg, p_carr.lat.deg
    except Exception:
        return ar_num, None

    centroid = get_centroid_fast(best_frame, carr_lon, carr_lat)

    result = {
        'carr_lon': float(centroid.lon.deg) if centroid else carr_lon,
        'carr_lat': float(centroid.lat.deg) if centroid else carr_lat,
        'seed_date': chosen['date'],
        'seed_lat': chosen['lat'],
        'seed_lon': chosen['lon'],
        'seed_frame': os.path.basename(best_frame),
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
    skip_existing = _global_params.get('skip_existing', False)

    total_processed = 0
    total_skipped = 0
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

                if skip_existing and os.path.exists(save_path):
                    total_skipped += 1
                    continue

                fits.writeto(save_path, crop_data, overwrite=True)
                total_processed += 1
                cropped_ars.add(ar_num)
        except:
            continue
    
    return total_processed, total_skipped, cropped_ars

def crop_active_regions(skip_existing=False, only_ars=None, output_root=None, max_workers=None):
    """主函数。only_ars 给定时只裁这些编号，并只读它们出现过的日期。"""
    logger = setup_logging('step2_crop_regions')
    logger.info("="*60)
    logger.info("步骤2: 裁剪活动区域（多年份数据）- 开始")
    logger.info("="*60)
    if skip_existing:
        logger.info("增量模式: 跳过已存在的裁剪 FITS")
        print("增量模式: 跳过已存在的裁剪 FITS")
    
    noaa_path = output_root or get_path('fits_600_raw')
    ensure_directory(noaa_path)
    
    # 读取多年份SRS报告
    print("读取多年份SRS报告...")
    ar_raw_data, date_to_ars = build_ar_reference_coords_raw_multi_year()
    if only_ars:
        only_ars = {str(ar) for ar in only_ars}
        ar_raw_data = {ar: info for ar, info in ar_raw_data.items() if ar in only_ars}
        date_to_ars = {
            day: [ar for ar in ars if ar in only_ars]
            for day, ars in date_to_ars.items()
        }
        date_to_ars = {day: ars for day, ars in date_to_ars.items() if ars}
        missing = sorted(only_ars - set(ar_raw_data))
        if missing:
            print(f"SRS 第 I 部分没有这些编号: {', '.join(missing)}")
    print(f"找到 {len(ar_raw_data)} 个活动区")
    logger.info(f"找到 {len(ar_raw_data)} 个活动区")
    
    # 获取所有FITS文件
    print("扫描多年份FITS文件...")
    fits_files = get_all_fits_files()
    if only_ars:
        fits_files = [
            path for path in fits_files
            if (extract_time_from_fits_filename(path) or "")[:10].replace("-", "") in date_to_ars
        ]
    print(f"找到 {len(fits_files)} 个FITS文件")
    logger.info(f"找到 {len(fits_files)} 个FITS文件")
    
    if not fits_files:
        logger.warning("未找到FITS文件")
        return
    
    # 建立FITS索引
    fits_by_date = build_fits_index_multi_year(fits_files)
    
    # 计算精确锚点
    ar_optimized_data = calculate_accurate_anchors(ar_raw_data, date_to_ars, fits_by_date)
    for ar_num in sorted(ar_optimized_data, key=lambda x: int(x)):
        info = ar_optimized_data[ar_num]
        print(
            f"  AR{ar_num}: 种子 {info.get('seed_date')} "
            f"lat={info.get('seed_lat')} lon={info.get('seed_lon')} "
            f"帧 {info.get('seed_frame')} "
            f"-> Carrington ({info['carr_lon']:.3f}, {info['carr_lat']:.3f})"
        )
    
    # 准备多进程参数
    global_params = {
        'crop_size': PARAMS['crop_size'],
        'noaa_path': noaa_path,
        'skip_existing': skip_existing,
    }
    
    batch_size = PARAMS.get('preload_count', 20)
    batches = [fits_files[i:i + batch_size] for i in range(0, len(fits_files), batch_size)]
    
    max_workers = max_workers or PARAMS.get('max_workers', 12)
    print(f"\n开始并行处理 (进程数={max_workers})...")
    logger.info(f"开始并行处理 (进程数={max_workers})")
    
    total_processed = 0
    total_skipped = 0
    all_cropped_ars = set()
    
    with Pool(max_workers, initializer=init_worker, initargs=(ar_optimized_data, date_to_ars, global_params)) as pool:
        results = list(tqdm(
            pool.imap_unordered(process_fits_batch, batches),
            total=len(batches),
            desc="裁剪进度"
        ))
        for count, skipped, cropped_set in results:
            total_processed += count
            total_skipped += skipped
            all_cropped_ars.update(cropped_set)
    
    print(f"\n步骤2完成: 新生成 {total_processed} 个文件，跳过 {total_skipped} 个")
    print(f"  - 成功裁剪的活动区数量: {len(all_cropped_ars)}")
    logger.info(f"步骤2完成: 新生成 {total_processed} 个文件，跳过 {total_skipped} 个")
    logger.info(f"成功裁剪的活动区数量: {len(all_cropped_ars)}")
    return {
        'processed': total_processed,
        'skipped': total_skipped,
        'cropped_ars': len(all_cropped_ars),
    }

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Step2: 裁剪活动区域 FITS')
    parser.add_argument(
        '--skip-existing',
        action='store_true',
        help='跳过已存在的裁剪 FITS 文件（增量补数）',
    )
    parser.add_argument(
        '--ars',
        default=None,
        help='只裁这些活动区，逗号分隔，例如 1302,1305',
    )
    parser.add_argument(
        '--output',
        default=None,
        help='未旋转裁剪的输出根目录，默认 config 里的 fits_600_raw',
    )
    parser.add_argument('--workers', type=int, default=None)
    args = parser.parse_args()
    only_ars = [item.strip() for item in args.ars.split(',')] if args.ars else None
    crop_active_regions(
        skip_existing=args.skip_existing,
        only_ars=only_ars,
        output_root=args.output,
        max_workers=args.workers,
    )
