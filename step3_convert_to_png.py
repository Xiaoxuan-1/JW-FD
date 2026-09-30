# -*- coding: utf-8 -*-
"""
步骤3: 将FITS文件转换为PNG图像
输入: 裁剪后的FITS文件 (原始方向)
输出: PNG图像文件 (翻转修正后的视觉方向)

处理:
1. np.fliplr（左右翻转），将 HMI 裁剪修正为上北左东（论文：mirrored left to right）。
2. 归一化与 JW-FD-fixed / Universe 论文一致：
   NaN → 0 G，再 clip 到 ±B_th，线性映射
   (B + B_th) / (2 B_th) * 255 → uint8。
   0 G 对应灰阶 127。默认 B_th = 800 G；十档 200–2000 G，步长 200 G。
"""

import argparse
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


def fits_to_png_path(fits_file, input_folder, output_folder):
    """FITS 路径映射为对应 PNG 输出路径（保持子目录结构）。"""
    subdir = os.path.dirname(fits_file)
    relative_path = os.path.relpath(subdir, input_folder)
    output_dir = os.path.join(output_folder, relative_path)
    return os.path.join(output_dir, os.path.basename(fits_file).replace('.fits', '.png'))


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
    skip_existing = _global_params.get('skip_existing', False)
    logger = setup_logging('step3_convert_png')

    # 第一步：预加载所有文件到内存
    preloaded = []
    skipped = 0
    for fits_file in batch:
        output_file = fits_to_png_path(fits_file, input_folder, output_folder)
        if skip_existing and os.path.exists(output_file):
            skipped += 1
            continue

        try:
            import warnings
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                with fits.open(fits_file, memmap=False) as hdul:
                    raw_data = hdul[0].data.astype('float32')
                    data = np.fliplr(raw_data).copy()
                    preloaded.append((fits_file, data))

                for warning in w:
                    if "truncated" in str(warning.message):
                        logger.warning(f"FITS文件截断: {fits_file} - {warning.message}")

        except Exception as e:
            preloaded.append((fits_file, None, str(e)))

    # 第二步：从内存处理
    processed = 0
    failed_files = []
    for item in preloaded:
        if len(item) == 3:
            failed_files.append((item[0], item[2]))
            continue

        fits_file, data = item
        try:
            output_file = fits_to_png_path(fits_file, input_folder, output_folder)
            if skip_existing and os.path.exists(output_file):
                skipped += 1
                continue

            output_dir = os.path.dirname(output_file)
            os.makedirs(output_dir, exist_ok=True)

            image_data = hmi_norm(data, threshold=threshold)
            img = Image.fromarray(image_data)
            img.save(output_file)
            processed += 1

        except Exception as e:
            failed_files.append((fits_file, str(e)))

    del preloaded
    gc.collect()
    return processed, failed_files, skipped


def convert_to_png(skip_existing=False):
    """主函数：转换FITS文件为PNG"""
    logger = setup_logging('step3_convert_png')
    logger.info("开始转换FITS文件为PNG (含视觉修正)...")

    input_folder = get_path('fits_600')
    output_folder = get_path('png_600')
    threshold = PARAMS['mag_threshold']

    ensure_directory(output_folder)
    logger.info(f"使用阈值: {threshold}")
    logger.info(f"输出目录: {output_folder}")
    if skip_existing:
        logger.info("增量模式: 跳过已存在的 PNG")
        print("增量模式: 跳过已存在的 PNG")

    fits_files = []
    for subdir, dirs, files in os.walk(input_folder):
        for file in files:
            if file.endswith(".fits"):
                fits_files.append(os.path.join(subdir, file))

    fits_files.sort()
    total_before = len(fits_files)
    fits_files = [f for f in fits_files if year_in_range(extract_year_from_filename(f))]
    filter_msg = f"年份过滤 [{START_YEAR}, {END_YEAR}]：{total_before} -> {len(fits_files)}"
    logger.info(filter_msg)
    print(filter_msg)

    skipped_prefilter = 0
    if skip_existing:
        to_process = []
        for fits_file in fits_files:
            png_path = fits_to_png_path(fits_file, input_folder, output_folder)
            if os.path.exists(png_path):
                skipped_prefilter += 1
            else:
                to_process.append(fits_file)
        skip_msg = f"跳过已存在 PNG：{skipped_prefilter}，待处理：{len(to_process)}"
        logger.info(skip_msg)
        print(skip_msg)
        fits_files = to_process

    logger.info(f"找到{len(fits_files)}个FITS文件待转换")
    print(f"找到 {len(fits_files)} 个FITS文件待转换")

    if not fits_files:
        print(f"步骤3完成: 无需转换 (跳过 {skipped_prefilter} 个已存在 PNG)")
        return {'processed': 0, 'skipped': skipped_prefilter, 'failed': 0}

    params = {
        'input_folder': input_folder,
        'output_folder': output_folder,
        'threshold': threshold,
        'skip_existing': skip_existing,
    }

    total_processed = 0
    total_skipped = skipped_prefilter
    all_failed = []

    if PARAMS['use_multiprocess']:
        max_workers = PARAMS['max_workers'] or cpu_count()
        batch_size = PARAMS.get('preload_count', 40)
        batches = [fits_files[i:i + batch_size] for i in range(0, len(fits_files), batch_size)]

        print(f"使用 {max_workers} 个进程，每批 {batch_size} 个文件")

        with Pool(max_workers, initializer=init_worker, initargs=(params,)) as pool:
            for batch_count, failed_list, batch_skipped in tqdm(
                pool.imap_unordered(process_batch, batches),
                total=len(batches),
                desc="转换PNG",
            ):
                total_processed += batch_count
                total_skipped += batch_skipped
                all_failed.extend(failed_list)
    else:
        init_worker(params)
        batch_size = 50
        batches = [fits_files[i:i + batch_size] for i in range(0, len(fits_files), batch_size)]

        for batch in tqdm(batches, desc="转换PNG"):
            count, failed, batch_skipped = process_batch(batch)
            total_processed += count
            total_skipped += batch_skipped
            all_failed.extend(failed)

    if all_failed:
        logger.warning(f"共有 {len(all_failed)} 个文件转换失败:")
        for failed_file, error in all_failed:
            logger.error(f"  失败文件: {failed_file}, 错误: {error}")
        print(f"警告: {len(all_failed)} 个文件转换失败，详见日志")

    summary = {
        'processed': total_processed,
        'skipped': total_skipped,
        'failed': len(all_failed),
    }
    logger.info(
        f"转换完成: 新生成 {total_processed}，跳过 {total_skipped}，失败 {len(all_failed)}"
    )
    print(
        f"步骤3完成: 新生成 {total_processed}，跳过 {total_skipped}，"
        f"失败 {len(all_failed)} (已执行翻转修正)"
    )
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Step3: FITS 转 PNG")
    parser.add_argument(
        '--skip-existing',
        action='store_true',
        help='跳过已存在的 PNG 文件（增量补数）',
    )
    args = parser.parse_args()
    convert_to_png(skip_existing=args.skip_existing)
