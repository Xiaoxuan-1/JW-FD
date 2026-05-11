# -*- coding: utf-8 -*-
"""
步骤3: 将FITS文件转换为PNG图像 (修正版)
输入: 裁剪后的FITS文件 (原始方向)
输出: PNG图像文件 (翻转修正后的视觉方向)

修正点:
在此步骤进行 np.fliplr (左右翻转)，将 HMI 的原始数据修正为符合人类直觉的"上北左东"方向。
"""

import os
import gc
import numpy as np  # 必须导入 numpy
from astropy.io import fits
from PIL import Image
from tqdm import tqdm
from multiprocessing import Pool, cpu_count

from config import PARAMS, START_YEAR, END_YEAR, year_in_range, get_path
from utils import setup_logging, hmi_norm, ensure_directory, extract_year_from_filename

# 全局变量
_global_params = None

def init_worker(params):
    """初始化worker进程"""
    global _global_params
    _global_params = params

def process_batch(batch):
    """批量处理多个文件 - 先预加载到内存再处理"""
    global _global_params
    input_folder = _global_params['input_folder']
    output_folder = _global_params['output_folder']
    threshold = _global_params['threshold']
    logger = setup_logging('step3_convert_png')
    
    # 第一步：预加载所有文件到内存
    preloaded = []
    for fits_file in batch:
        try:
            # 捕获astropy的警告并记录文件名
            import warnings
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                with fits.open(fits_file, memmap=False) as hdul:
                    # 读取原始数据
                    # Step 2 生成的 FITS 通常数据在 PrimaryHDU (索引0)
                    raw_data = hdul[0].data.astype('float32')
                    
                    # 【核心修正】：在这里进行左右翻转！
                    # Step 2 保存的是 HMI 原始镜像数据 (东在右)
                    # 这里翻转后，PNG 就会显示为标准的 (东在左)
                    data = np.fliplr(raw_data).copy()
                    
                    preloaded.append((fits_file, data))
                
                # 检查是否有截断警告
                for warning in w:
                    if "truncated" in str(warning.message):
                        logger.warning(f"FITS文件截断: {fits_file} - {warning.message}")
                        
        except Exception as e:
            preloaded.append((fits_file, None, str(e)))
    
    # 第二步：从内存处理
    processed = 0
    failed_files = []
    for item in preloaded:
        if len(item) == 3:  # 加载失败，item结构为 (file, None, error_msg)
            failed_files.append((item[0], item[2]))
            continue
        
        fits_file, data = item
        try:
            # 1. 确定输出路径，保持目录结构
            # 例如: fits_600/3536/xxx.fits -> png_600/3536/xxx.png
            subdir = os.path.dirname(fits_file)
            relative_path = os.path.relpath(subdir, input_folder)
            output_dir = os.path.join(output_folder, relative_path)
            os.makedirs(output_dir, exist_ok=True)
            
            output_file = os.path.join(output_dir, os.path.basename(fits_file).replace('.fits', '.png'))
            
            # 2. 归一化 (Mapping到 0-255)
            # hmi_norm 内部处理了 NaN 和 阈值截断
            image_data = hmi_norm(data, threshold=threshold)
            
            # 3. 保存为 PNG
            img = Image.fromarray(image_data)
            img.save(output_file)
            processed += 1
            
        except Exception as e:
            failed_files.append((fits_file, str(e)))
    
    # 清理内存
    del preloaded
    gc.collect()
    return processed, failed_files

def convert_to_png():
    """主函数：转换FITS文件为PNG"""
    logger = setup_logging('step3_convert_png')
    logger.info("开始转换FITS文件为PNG (含视觉修正)...")
    
    input_folder = get_path('fits_600')
    output_folder = get_path('png_600')
    threshold = PARAMS['mag_threshold']
    
    ensure_directory(output_folder)
    logger.info(f"使用阈值: {threshold}")
    logger.info(f"输出目录: {output_folder}")
    
    # 收集所有FITS文件 (递归查找)
    fits_files = []
    for subdir, dirs, files in os.walk(input_folder):
        for file in files:
            if file.endswith(".fits"):
                fits_files.append(os.path.join(subdir, file))
    
    # 排序以保证处理顺序一致
    fits_files.sort()
    total_before = len(fits_files)
    fits_files = [f for f in fits_files if year_in_range(extract_year_from_filename(f))]
    filter_msg = f"年份过滤 [{START_YEAR}, {END_YEAR}]：{total_before} -> {len(fits_files)}"
    logger.info(filter_msg)
    print(filter_msg)

    logger.info(f"找到{len(fits_files)}个FITS文件（年份过滤后）")
    print(f"找到 {len(fits_files)} 个FITS文件（年份过滤后）")

    if not fits_files:
        print("没有找到FITS文件，请先运行 Step 2")
        return
    
    params = {
        'input_folder': input_folder,
        'output_folder': output_folder,
        'threshold': threshold
    }
    
    if PARAMS['use_multiprocess']:
        max_workers = PARAMS['max_workers'] or cpu_count()
        batch_size = PARAMS.get('preload_count', 40)
        
        # 分批
        batches = [fits_files[i:i+batch_size] for i in range(0, len(fits_files), batch_size)]
        
        print(f"使用 {max_workers} 个进程，每批 {batch_size} 个文件")
        
        total_processed = 0
        all_failed = []
        
        # 使用 imap_unordered 并显示总进度条
        with Pool(max_workers, initializer=init_worker, initargs=(params,)) as pool:
            for batch_count, failed_list in tqdm(pool.imap_unordered(process_batch, batches), 
                                                 total=len(batches), desc="转换PNG"):
                total_processed += batch_count
                all_failed.extend(failed_list)
        
        # 记录失败文件
        if all_failed:
            logger.warning(f"共有 {len(all_failed)} 个文件转换失败:")
            for failed_file, error in all_failed:
                logger.error(f"  失败文件: {failed_file}, 错误: {error}")
            print(f"警告: {len(all_failed)} 个文件转换失败，详见日志")
            
    else:
        # 单进程模式 (调试用)
        init_worker(params)
        total_processed = 0
        all_failed = []
        # 单进程也分批，避免一次性加载过多导致内存溢出
        batch_size = 50
        batches = [fits_files[i:i+batch_size] for i in range(0, len(fits_files), batch_size)]
        
        for batch in tqdm(batches, desc="转换PNG"):
            count, failed = process_batch(batch)
            total_processed += count
            all_failed.extend(failed)
        
        if all_failed:
            logger.warning(f"共有 {len(all_failed)} 个文件转换失败")

    logger.info(f"转换完成，共生成 {total_processed} 张图片")
    print(f"步骤3完成: FITS转PNG，共处理 {total_processed} 个文件 (已执行翻转修正)")

if __name__ == "__main__":
    convert_to_png()