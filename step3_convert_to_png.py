# -*- coding: utf-8 -*-
"""
步骤3: 将 rot180 后的 FITS 转为 PNG（单遍多阈值）

输入: JW-FD-fixed/fits_600（step2b 已 rot180，数组已是上北左东）
输出: 每个阈值一套 PNG

修正点:
1. FITS 已在 step2b 修正 HMI 180°；此处仅 np.flipud，抵消 PNG 看图软件「第 0 行在顶」与 ds9 的差异。
2. 每个 FITS 只打开一次，同时输出全部 png_thresholds。
3. 归一化: 固定 ±threshold、NaN 填 0 G。
4. compress_level=1。

注意：BLAS 线程数必须在 numpy 加载前设置才生效。multiprocessing 默认 fork，
子进程继承父进程已初始化的 BLAS 线程池，因此在 init_worker 里设置为时已晚。
这里统一放在模块顶部、任何 numpy/PIL 导入之前。
"""

import os

# ---- 必须早于 numpy 导入：避免 64 个进程各自开满 BLAS 线程互相争抢 ----
for _var in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS',
             'OPENBLAS_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ.setdefault(_var, '1')

import argparse
import gc
import numpy as np  # 必须导入 numpy
from astropy.io import fits
from PIL import Image
from tqdm import tqdm
from multiprocessing import Pool, cpu_count

from config import (
    PARAMS,
    START_YEAR,
    END_YEAR,
    year_in_range,
    get_path,
    get_png_dir,
    get_png_thresholds,
)
from utils import setup_logging, ensure_directory, extract_year_from_filename

# 全局变量
_global_params = None


def fits_to_png_path(fits_file, input_folder, output_folder):
    """FITS 路径映射为对应 PNG 输出路径（保持子目录结构）。"""
    subdir = os.path.dirname(fits_file)
    relative_path = os.path.relpath(subdir, input_folder)
    output_dir = os.path.join(output_folder, relative_path)
    return os.path.join(output_dir, os.path.basename(fits_file).replace('.fits', '.png'))


def png_paths_for_thresholds(fits_file, input_folder, output_roots):
    """返回 {threshold: png_path}，output_roots 为 {threshold: 输出根目录}。"""
    return {
        th: fits_to_png_path(fits_file, input_folder, root)
        for th, root in output_roots.items()
    }


def normalize_to_uint8(arr_nan_filled, threshold):
    """对已完成 flipud 与 NaN 填充的数组按单个阈值定标到 uint8。"""
    clipped = np.clip(arr_nan_filled, -threshold, threshold)
    return ((clipped + threshold) / (2.0 * threshold) * 255.0).astype('uint8')


def init_worker(params):
    """初始化worker进程"""
    global _global_params
    _global_params = params


def process_batch(batch):
    """批量处理多个文件 - 先预加载到内存再处理，一次读盘写出全部阈值。"""
    global _global_params
    input_folder = _global_params['input_folder']
    output_roots = _global_params['output_roots']
    compress_level = _global_params['compress_level']
    skip_existing = _global_params.get('skip_existing', False)
    logger = setup_logging('step3_convert_png')

    stats = {
        'frames': 0,        # 实际读取并转换的 FITS 帧数
        'pngs': 0,          # 新写出的 PNG 张数
        'frames_skipped': 0,  # 所有阈值 PNG 均已存在而整帧跳过
        'pngs_skipped': 0,    # 单个阈值 PNG 已存在而跳过
    }

    # 第一步：预加载所有文件到内存（NaN 填充在这里做一次，供所有阈值复用）
    preloaded = []
    for fits_file in batch:
        out_paths = png_paths_for_thresholds(fits_file, input_folder, output_roots)
        if skip_existing:
            missing = {th: p for th, p in out_paths.items() if not os.path.exists(p)}
            stats['pngs_skipped'] += len(out_paths) - len(missing)
            if not missing:
                stats['frames_skipped'] += 1
                continue
            out_paths = missing

        try:
            import warnings
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                with fits.open(fits_file, memmap=False) as hdul:
                    raw_data = hdul[0].data.astype('float32')
                    data = np.flipud(raw_data).copy()
                    data[np.isnan(data)] = 0.0
                    preloaded.append((fits_file, data, out_paths))

                for warning in w:
                    if "truncated" in str(warning.message):
                        logger.warning(f"FITS文件截断: {fits_file} - {warning.message}")

        except Exception as e:
            preloaded.append((fits_file, None, None, str(e)))

    # 第二步：从内存处理
    failed_files = []
    for item in preloaded:
        if len(item) == 4:
            failed_files.append((item[0], item[3]))
            continue

        fits_file, data, out_paths = item
        try:
            for threshold, output_file in sorted(out_paths.items()):
                os.makedirs(os.path.dirname(output_file), exist_ok=True)
                image_data = normalize_to_uint8(data, threshold)
                Image.fromarray(image_data).save(output_file, compress_level=compress_level)
                stats['pngs'] += 1
            stats['frames'] += 1

        except Exception as e:
            failed_files.append((fits_file, str(e)))

    del preloaded
    gc.collect()
    return stats, failed_files


def convert_to_png(skip_existing=False, thresholds=None, only_ars=None):
    """主函数：单遍读取 FITS，同时生成多个阈值的 PNG。"""
    logger = setup_logging('step3_convert_png')
    logger.info("开始转换FITS文件为PNG (含视觉修正, 单遍多阈值)...")

    input_folder = get_path('fits_600')
    thresholds = sorted({int(t) for t in (thresholds or get_png_thresholds())})
    output_roots = {th: get_png_dir(th) for th in thresholds}

    for root in output_roots.values():
        ensure_directory(root)

    logger.info(f"使用阈值: {thresholds}")
    logger.info(f"输入目录: {input_folder}")
    for th in thresholds:
        logger.info(f"  Th{th} -> {output_roots[th]}")
    print(f"阈值: {thresholds}")
    print(f"输入: {input_folder}")
    print(f"输出根目录: {os.path.dirname(output_roots[thresholds[0]])}")

    if skip_existing:
        logger.info("增量模式: 仅补齐缺失的 PNG（按阈值逐个判断）")
        print("增量模式: 仅补齐缺失的 PNG（按阈值逐个判断）")

    only_ars = {str(ar) for ar in only_ars} if only_ars else None
    fits_files = []
    for subdir, dirs, files in os.walk(input_folder):
        if only_ars and os.path.abspath(subdir) == os.path.abspath(input_folder):
            dirs[:] = [name for name in dirs if name in only_ars]
        elif only_ars and os.path.basename(subdir) not in only_ars:
            continue
        for file in files:
            if file.endswith(".fits"):
                fits_files.append(os.path.join(subdir, file))

    fits_files.sort()
    total_before = len(fits_files)
    fits_files = [f for f in fits_files if year_in_range(extract_year_from_filename(f))]
    filter_msg = f"年份过滤 [{START_YEAR}, {END_YEAR}]：{total_before} -> {len(fits_files)}"
    logger.info(filter_msg)
    print(filter_msg)

    frames_skipped_prefilter = 0
    pngs_skipped_prefilter = 0
    if skip_existing:
        to_process = []
        for fits_file in fits_files:
            out_paths = png_paths_for_thresholds(fits_file, input_folder, output_roots)
            existing = sum(1 for p in out_paths.values() if os.path.exists(p))
            if existing == len(out_paths):
                frames_skipped_prefilter += 1
                pngs_skipped_prefilter += existing
            else:
                to_process.append(fits_file)
        skip_msg = (
            f"整帧跳过 {frames_skipped_prefilter} 帧（{pngs_skipped_prefilter} 张 PNG 已存在），"
            f"待处理 {len(to_process)} 帧"
        )
        logger.info(skip_msg)
        print(skip_msg)
        fits_files = to_process

    logger.info(f"待转换 {len(fits_files)} 帧 x {len(thresholds)} 阈值")
    print(f"待转换 {len(fits_files)} 帧 x {len(thresholds)} 阈值 "
          f"= 最多 {len(fits_files) * len(thresholds)} 张 PNG")

    if not fits_files:
        print(f"步骤3完成: 无需转换 (跳过 {frames_skipped_prefilter} 帧)")
        return {
            'thresholds': thresholds,
            'frames_processed': 0,
            'pngs_written': 0,
            'frames_skipped': frames_skipped_prefilter,
            'pngs_skipped': pngs_skipped_prefilter,
            'failed': 0,
        }

    params = {
        'input_folder': input_folder,
        'output_roots': output_roots,
        'compress_level': PARAMS['png_compress_level'],
        'skip_existing': skip_existing,
    }

    total = {
        'frames': 0,
        'pngs': 0,
        'frames_skipped': frames_skipped_prefilter,
        'pngs_skipped': pngs_skipped_prefilter,
    }
    all_failed = []

    def accumulate(batch_stats):
        for key in total:
            total[key] += batch_stats[key]

    if PARAMS['use_multiprocess']:
        max_workers = PARAMS['max_workers'] or cpu_count()
        batch_size = PARAMS.get('preload_count', 40)
        batches = [fits_files[i:i + batch_size] for i in range(0, len(fits_files), batch_size)]

        print(f"使用 {max_workers} 个进程，每批 {batch_size} 个文件")

        with Pool(max_workers, initializer=init_worker, initargs=(params,)) as pool:
            for batch_stats, failed_list in tqdm(
                pool.imap_unordered(process_batch, batches),
                total=len(batches),
                desc="转换PNG",
            ):
                accumulate(batch_stats)
                all_failed.extend(failed_list)
    else:
        init_worker(params)
        batch_size = 50
        batches = [fits_files[i:i + batch_size] for i in range(0, len(fits_files), batch_size)]

        for batch in tqdm(batches, desc="转换PNG"):
            batch_stats, failed = process_batch(batch)
            accumulate(batch_stats)
            all_failed.extend(failed)

    if all_failed:
        logger.warning(f"共有 {len(all_failed)} 个文件转换失败:")
        for failed_file, error in all_failed:
            logger.error(f"  失败文件: {failed_file}, 错误: {error}")
        print(f"警告: {len(all_failed)} 个文件转换失败，详见日志")

    summary = {
        'thresholds': thresholds,
        'frames_processed': total['frames'],
        'pngs_written': total['pngs'],
        'frames_skipped': total['frames_skipped'],
        'pngs_skipped': total['pngs_skipped'],
        'failed': len(all_failed),
    }
    logger.info(
        f"转换完成: 处理 {total['frames']} 帧 -> 新写 {total['pngs']} 张 PNG，"
        f"整帧跳过 {total['frames_skipped']} 帧 / 单张跳过 {total['pngs_skipped']} 张，"
        f"失败 {len(all_failed)}"
    )
    print(
        f"步骤3完成: 处理 {total['frames']} 帧 -> 新写 {total['pngs']} 张 PNG，"
        f"整帧跳过 {total['frames_skipped']} 帧，失败 {len(all_failed)} (已执行翻转修正)"
    )
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Step3: FITS 转 PNG（单遍多阈值）")
    parser.add_argument(
        '--skip-existing',
        action='store_true',
        help='跳过已存在的 PNG 文件（按阈值逐个判断，只补缺失的那几个阈值）',
    )
    parser.add_argument(
        '--thresholds',
        nargs='+',
        type=int,
        default=None,
        help=f"只生成指定阈值，默认全部 {PARAMS['png_thresholds']}",
    )
    parser.add_argument('--ars', default=None, help='只转换这些活动区，逗号分隔')
    args = parser.parse_args()
    only_ars = [item.strip() for item in args.ars.split(',')] if args.ars else None
    convert_to_png(skip_existing=args.skip_existing, thresholds=args.thresholds, only_ars=only_ars)
