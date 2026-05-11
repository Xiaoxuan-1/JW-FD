# -*- coding: utf-8 -*-
"""
Demo: 高性能活动区跟踪 (最终修正版)
修正点：
1. 坐标系方向：明确 E(左) 为负，W(右) 为正，符合黑子从左向右移动规律。
2. 日期匹配：修复了 FITS 文件名日期截取长度错误的问题。
3. 性能：保持多进程 + Memmap 读取。
"""

import glob
import os
import re
import numpy as np
import sunpy.map
from sunpy.coordinates import frames
import astropy.units as u
from astropy.coordinates import SkyCoord
from astropy.time import Time
import astropy.io.fits as fits
import imageio
from scipy.ndimage import center_of_mass
from concurrent.futures import ProcessPoolExecutor
import functools
import warnings

warnings.filterwarnings('ignore')

# ========== 配置 ==========
DEMO_OUTPUT = "Output/demo_final"
FITS_FOLDER = "2024_Fits/HMI_M_20240101_0301/"
SRS_FOLDER = "2024_SRS/"
CROP_SIZE = 300       
SEARCH_SIZE = 80      # 日面中心，1°误差约35像素，SRS报告精度为1°。    
MAX_LON = 60          # 稍微放宽经度限制，确保能抓到边缘
MAG_THRESHOLD = 200   
CALC_THRESHOLD = 100  
NUM_WORKERS = 8       
TEST_ARS = ['3536']   
# =========================

def extract_time_from_fits_filename(filename):
    base = os.path.basename(filename)
    match = re.search(r'(\d{8})_(\d{6})', base)
    if match:
        d, t = match.group(1), match.group(2)
        return f"{d[:4]}-{d[4:6]}-{d[6:8]}T{t[:2]}:{t[2:4]}:{t[4:]}"
    return None

def date_to_time(date_str):
    return Time(f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}T00:00:00")

def hmi_norm(image, threshold=200):
    image = np.nan_to_num(image)
    image = np.clip(image, -threshold, threshold)
    min_val, max_val = -threshold, threshold
    normalized = (image - min_val) / (max_val - min_val) * 255
    return normalized.astype('uint8')

def read_srs_coords():
    """读取 SRS (修正经度符号：E为负，W为正)"""
    ar_first_coords = {}
    date_to_ars = {}
    srs_files = sorted(glob.glob(f"{SRS_FOLDER}*.txt"))
    
    for srs_file in srs_files:
        base = os.path.basename(srs_file)
        match = re.search(r'(\d{8})', base)
        if not match: continue
        srs_date = match.group(1)

        data = []
        with open(srs_file, 'r') as f:
            lines = f.readlines()
            
        is_data = False
        for line in lines:
            if "Nmbr" in line and "Location" in line: is_data = True; continue
            if is_data:
                if line.strip() == "" or "IA" in line or "II" in line: break
                parts = line.split()
                if len(parts) >= 2: data.append(parts)
        
        today_ars = []
        for row in data:
            try:
                nmbr, loc = row[0], row[1]
                lat_dir, lat_val = loc[0], float(loc[1:3])
                lon_dir, lon_val = loc[3], float(loc[4:])
                
                lat = lat_val if lat_dir == 'N' else -lat_val
                
                # 【核心修正】E (左边) 设为负，W (右边) 设为正
                # 这样随时间推移 (左->右)，数值从 -60 变到 +60，中间经过 0
                real_lon = -lon_val if lon_dir == 'E' else lon_val
                
                today_ars.append(nmbr)
                if nmbr not in ar_first_coords:
                    ar_first_coords[nmbr] = {'lat': lat, 'lon': real_lon, 'date': srs_date}
            except: continue
        date_to_ars[srs_date] = today_ars
    return ar_first_coords, date_to_ars

def build_fits_index(fits_files):
    fits_by_date = {}
    for f in fits_files:
        t = extract_time_from_fits_filename(f)
        if t:
            # 【修复】截取前10位(2024-01-01)再替换，得到8位日期
            date = t[:10].replace("-", "") 
            if date not in fits_by_date: fits_by_date[date] = []
            fits_by_date[date].append(f)
    return fits_by_date

def process_single_frame_worker(fits_path, target_carr_lon, target_carr_lat, output_dir):
    try:
        hmi_map = sunpy.map.Map(fits_path, memmap=True)
        
        target_coord = SkyCoord(
            lon=target_carr_lon*u.deg, lat=target_carr_lat*u.deg,
            frame=frames.HeliographicCarrington(obstime=hmi_map.date, observer='earth')
        )
        
        # 经度检查
        stony = target_coord.transform_to(frames.HeliographicStonyhurst(obstime=hmi_map.date))
        if abs(stony.lon.deg) > MAX_LON: return None 

        pix = hmi_map.world_to_pixel(target_coord)
        x, y = int(pix.x.value), int(pix.y.value)
        
        if not (CROP_SIZE <= x <= 4096-CROP_SIZE and CROP_SIZE <= y <= 4096-CROP_SIZE): return None

        crop = hmi_map.data[y-CROP_SIZE:y+CROP_SIZE, x-CROP_SIZE:x+CROP_SIZE].copy()
        # HMI 的倒置问题是处理太阳数据最常见的坑之一
        # HMI 卫星为了光学设计，相机的安装角度通常是旋转了 180 度的 (CROTA2 ≈ 180.0)。当你使用 hmi_map.data 直接读取 numpy 数组时，你读到的是原始的、倒着的数据。
        # 第二层：FITS 与 PNG 的原点冲突 (数据层);FITS 标准 (天文界)：原点 (0,0) 在 左下角。Y 轴向上增加。Numpy/PNG 标准 (计算机界)：原点 (0,0) 在 左上角。Y 轴向下增加。
        # 当你直接把 FITS 数据保存为 PNG 时，计算机把 FITS 数据的“第 0 行”（天文学上的底部）画在了图片的“最上面”。这等价于做了一次垂直翻转 (FlipUD)。

        crop = np.fliplr(crop)
        
        
        t_str = hmi_map.date.strftime("%Y%m%d_%H%M%S")
        out_path = os.path.join(output_dir, f"{t_str}.png")
        imageio.imwrite(out_path, hmi_norm(crop, MAG_THRESHOLD))
        return out_path
    except: return None



def get_centroid_fast(fits_path, rough_lon, rough_lat):
    print(f"  计算重心参考帧: {os.path.basename(fits_path)}")
    try:
        m = sunpy.map.Map(fits_path)
        
        # 1. SRS 原始坐标
        p_rough = SkyCoord(lon=rough_lon*u.deg, lat=rough_lat*u.deg, 
                           frame=frames.HeliographicCarrington(obstime=m.date, observer='earth'))
        pix = m.world_to_pixel(p_rough)
        cx, cy = int(pix.x.value), int(pix.y.value)
        
        # 2. 截取搜索框 (使用较小的 SEARCH_SIZE，例如 120)
        # 建议在上面配置里把 SEARCH_SIZE 改为 120
        y0, y1 = max(0, cy - SEARCH_SIZE), min(4096, cy + SEARCH_SIZE)
        x0, x1 = max(0, cx - SEARCH_SIZE), min(4096, cx + SEARCH_SIZE)
        
        sub = np.nan_to_num(m.data[y0:y1, x0:x1])
        abs_sub = np.abs(sub)
        
        # 3. 计算重心
        mask = abs_sub > CALC_THRESHOLD
        if np.sum(mask) == 0: 
            print("    [提示] 无强磁场，使用 SRS 原始坐标")
            return p_rough
        
        dy, dx = center_of_mass(abs_sub * mask)
        new_y, new_x = y0 + dy, x0 + dx
        
        # 4. 【新增】安全检查：防跑偏
        # 计算新中心和 SRS 中心的像素距离
        dist = np.sqrt((new_x - cx)**2 + (new_y - cy)**2)
        
        # 如果修正量超过 150 像素 (约 4-5 度)，说明可能吸到了隔壁的大黑子
        if dist > 150:
            print(f"    [警告] 重心修正量过大 ({dist:.1f} px)，可能受到邻近活动区干扰。强制使用 SRS 坐标。")
            return p_rough
        
        print(f"    [成功] 重心修正: 偏移 {dist:.1f} px")
        return m.pixel_to_world(new_x*u.pix, new_y*u.pix).transform_to(frames.HeliographicCarrington(obstime=m.date, observer='earth'))
        
    except Exception as e:
        print(f"  重心计算错误: {e}")
        return None



def process_ar_pipeline(ar_num, ar_info, date_to_ars, fits_by_date):
    print(f"\n>>> 处理 AR{ar_num}...")
    out_dir = f"{DEMO_OUTPUT}/png/{ar_num}"
    os.makedirs(out_dir, exist_ok=True)
    
    # 找所有相关文件
    relevant_fits = []
    dates = sorted([d for d, ars in date_to_ars.items() if ar_num in ars])
    for d in dates:
        if d in fits_by_date: relevant_fits.extend(fits_by_date[d])
    relevant_fits.sort()
    
    if not relevant_fits: print("  无文件"); return []

    # 1. 估算初始 Carrington 坐标
    # 取第一帧将 Stonyhurst(SRS) 转为 Carrington
    try:
        m0 = sunpy.map.Map(relevant_fits[0], memmap=True)
        p_stony = SkyCoord(lon=ar_info['lon']*u.deg, lat=ar_info['lat']*u.deg, 
                           frame=frames.HeliographicStonyhurst(obstime=m0.date))
        p_carr = p_stony.transform_to(frames.HeliographicCarrington(obstime=m0.date, observer='earth'))
        carr_lon, carr_lat = p_carr.lon.deg, p_carr.lat.deg
        print(f"  SRS初始位置 (Stonyhurst): {ar_info['lon']}° (负=东/左, 正=西/右)")
    except: return []

    # 2. 扫描找最近中央经线的一帧
    print("  扫描最佳观测角度...")
    min_lon = 999
    best_fit = None
    
    # 跳跃扫描
    stride = max(1, len(relevant_fits)//40)
    for f in relevant_fits[::stride]:
        try:
            m = sunpy.map.Map(f, memmap=True)
            pc = SkyCoord(lon=carr_lon*u.deg, lat=carr_lat*u.deg, 
                          frame=frames.HeliographicCarrington(obstime=m.date, observer='earth'))
            cur_lon = pc.transform_to(frames.HeliographicStonyhurst(obstime=m.date)).lon.deg
            if abs(cur_lon) < min_lon:
                min_lon = abs(cur_lon)
                best_fit = f
        except: continue
        
    if not best_fit: best_fit = relevant_fits[len(relevant_fits)//2]
    print(f"  选中最佳帧: 距中心 {min_lon:.1f}°")

    # 3. 计算重心
    center_pt = get_centroid_fast(best_fit, carr_lon, carr_lat)
    if not center_pt: return []
    final_lon, final_lat = center_pt.lon.deg, center_pt.lat.deg
    
    # 4. 并行处理
    print(f"  开始并行裁剪 ({len(relevant_fits)} 帧)...")
    func = functools.partial(process_single_frame_worker, target_carr_lon=final_lon, target_carr_lat=final_lat, output_dir=out_dir)
    
    valid = []
    with ProcessPoolExecutor(max_workers=NUM_WORKERS) as ex:
        res = list(ex.map(func, relevant_fits))
    valid = [r for r in res if r]
    
    print(f"  生成 {len(valid)} 张图片")
    return valid

def main():
    os.makedirs(DEMO_OUTPUT, exist_ok=True)
    coords, dates = read_srs_coords()
    fits_files = sorted(glob.glob(f"{FITS_FOLDER}*.fits"))
    fits_idx = build_fits_index(fits_files)
    
    for ar in TEST_ARS:
        if ar in coords:
            pngs = process_ar_pipeline(ar, coords[ar], dates, fits_idx)
            if len(pngs) > 10:
                print("  生成视频...")
                vid = f"{DEMO_OUTPUT}/videos/AR{ar}.mp4"
                os.makedirs(os.path.dirname(vid), exist_ok=True)
                imgs = [imageio.imread(p) for p in sorted(pngs)]
                imageio.mimwrite(vid, imgs, fps=30, quality=8)
                print(f"  完成: {vid}")

if __name__ == "__main__":
    main()