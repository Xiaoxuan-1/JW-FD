# -*- coding: utf-8 -*-
"""
Step2b: 把 step2 裁出的 FITS 逐帧 rot180，写入 fits_600。

默认输入是 OUTPUT_PATH/fits_600_raw（step2 的未旋转裁剪）。
默认输出是 OUTPUT_PATH/fits_600，step3 及之后读这里。

HMI 全日面数组相对「上北左东」自带 180°；step2 裁切不改变朝向。
step2 的 writeto 只写数组、无 WCS，故 np.rot90(data, 2) 安全。

已发布的 /data/Datasets/JW-FD/fits_600 是旧裁剪，不含 2011 年 9 月重裁。
只有显式 ``--from-published`` 才从那里读，并且会覆盖修正版里同名活动区。

用法:
  python step2b_rotate_fits.py
  python step2b_rotate_fits.py --skip-existing
  python step2b_rotate_fits.py --from-published
"""

import os

for _var in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS',
             'OPENBLAS_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ.setdefault(_var, '1')

import argparse
import gc
import numpy as np
from astropy.io import fits
from tqdm import tqdm
from multiprocessing import Pool, cpu_count

from config import PARAMS, START_YEAR, END_YEAR, year_in_range, get_path
from utils import setup_logging, ensure_directory, extract_year_from_filename

_global_params = None
# fits.writeto of a 600x600 float64 array with one header block.
FLOAT64_BYTES = 600 * 600 * 8 + 2880


def source_to_output_path(src_file, input_folder, output_folder):
    subdir = os.path.dirname(src_file)
    rel = os.path.relpath(subdir, input_folder)
    out_dir = os.path.join(output_folder, rel)
    return os.path.join(out_dir, os.path.basename(src_file))


def init_worker(params):
    global _global_params
    _global_params = params


def process_batch(batch):
    global _global_params
    input_folder = _global_params['input_folder']
    output_folder = _global_params['output_folder']
    skip_existing = _global_params.get('skip_existing', False)
    logger = setup_logging('step2b_rotate_fits')

    processed = 0
    skipped = 0
    failed = []

    for src in batch:
        dst = source_to_output_path(src, input_folder, output_folder)
        if skip_existing and os.path.exists(dst):
            skipped += 1
            continue
        if _global_params.get('skip_float64') and os.path.isfile(dst):
            try:
                if os.path.getsize(dst) == FLOAT64_BYTES:
                    skipped += 1
                    continue
            except OSError:
                pass
        try:
            with fits.open(src, memmap=False) as hdul:
                data = hdul[0].data
                if data is None:
                    failed.append((src, '空数据'))
                    continue
                rotated = np.rot90(data, 2).copy()
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            fits.writeto(dst, rotated, overwrite=True)
            processed += 1
        except Exception as e:
            failed.append((src, str(e)))
            if 'truncated' in str(e).lower():
                logger.warning(f"FITS 截断: {src} - {e}")

    gc.collect()
    return processed, skipped, failed


def rotate_fits(skip_existing=False, skip_float64=False, max_workers=None,
                input_folder=None, output_folder=None):
    logger = setup_logging('step2b_rotate_fits')
    input_folder = input_folder or get_path('fits_600_raw')
    output_folder = output_folder or get_path('fits_600')
    if os.path.abspath(input_folder) == os.path.abspath(output_folder):
        raise ValueError(f"step2b 输入和输出不能是同一目录: {input_folder}")
    if not os.path.isdir(input_folder):
        print(f"Step2b 输入目录不存在，跳过: {input_folder}")
        return {'processed': 0, 'skipped': 0, 'failed': 0}
    ensure_directory(output_folder)

    logger.info(f"输入: {input_folder}")
    logger.info(f"输出: {output_folder}")
    print(f"Step2b rot180")
    print(f"  输入: {input_folder}")
    print(f"  输出: {output_folder}")
    if skip_existing:
        print("  增量模式: 跳过已存在的 FITS")
    if skip_float64:
        print(f"  续跑: 跳过已是 float64 的文件（{FLOAT64_BYTES} 字节）")

    fits_files = []
    for root, _, files in os.walk(input_folder):
        for name in files:
            if name.endswith('.fits'):
                fits_files.append(os.path.join(root, name))
    fits_files.sort()
    total_before = len(fits_files)
    fits_files = [f for f in fits_files if year_in_range(extract_year_from_filename(f))]
    print(f"年份过滤 [{START_YEAR}, {END_YEAR}]：{total_before} -> {len(fits_files)}")

    skipped_prefilter = 0
    if skip_existing:
        to_process = []
        for src in fits_files:
            dst = source_to_output_path(src, input_folder, output_folder)
            if os.path.exists(dst):
                skipped_prefilter += 1
            else:
                to_process.append(src)
        print(f"跳过已存在 {skipped_prefilter}，待处理 {len(to_process)}")
        fits_files = to_process

    if skip_float64:
        to_process = []
        for src in fits_files:
            dst = source_to_output_path(src, input_folder, output_folder)
            try:
                if os.path.isfile(dst) and os.path.getsize(dst) == FLOAT64_BYTES:
                    skipped_prefilter += 1
                    continue
            except OSError:
                pass
            to_process.append(src)
        print(f"跳过已是 float64 {skipped_prefilter}，待重写 {len(to_process)}")
        fits_files = to_process

    if not fits_files:
        print(f"Step2b 完成: 无需处理 (跳过 {skipped_prefilter})")
        return {'processed': 0, 'skipped': skipped_prefilter, 'failed': 0}

    params = {
        'input_folder': input_folder,
        'output_folder': output_folder,
        'skip_existing': skip_existing,
        'skip_float64': skip_float64,
    }

    total_processed = 0
    total_skipped = skipped_prefilter
    all_failed = []

    if PARAMS['use_multiprocess']:
        max_workers = max_workers or PARAMS['max_workers'] or cpu_count()
        batch_size = PARAMS.get('preload_count', 100)
        batches = [fits_files[i:i + batch_size] for i in range(0, len(fits_files), batch_size)]
        print(f"使用 {max_workers} 进程，每批 {batch_size} 个文件")

        with Pool(max_workers, initializer=init_worker, initargs=(params,)) as pool:
            for proc, skip, failed in tqdm(
                pool.imap_unordered(process_batch, batches),
                total=len(batches),
                desc="rot180",
            ):
                total_processed += proc
                total_skipped += skip
                all_failed.extend(failed)
    else:
        init_worker(params)
        for batch in tqdm([fits_files[i:i + 50] for i in range(0, len(fits_files), 50)], desc="rot180"):
            proc, skip, failed = process_batch(batch)
            total_processed += proc
            total_skipped += skip
            all_failed.extend(failed)

    if all_failed:
        logger.warning(f"失败 {len(all_failed)} 个文件")
        print(f"警告: {len(all_failed)} 个文件失败，详见日志")

    summary = {
        'processed': total_processed,
        'skipped': total_skipped,
        'failed': len(all_failed),
    }
    print(
        f"Step2b 完成: 新写 {total_processed}，跳过 {total_skipped}，"
        f"失败 {len(all_failed)}"
    )
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Step2b: FITS rot180')
    parser.add_argument('--skip-existing', action='store_true')
    parser.add_argument('--skip-float64', action='store_true',
                        help='跳过目标里已经是 600x600 float64 的文件')
    parser.add_argument('--input', default=None, help='未旋转裁剪目录，默认 fits_600_raw')
    parser.add_argument('--output', default=None, help='rot180 输出目录，默认 fits_600')
    parser.add_argument('--from-published', action='store_true',
                        help='从已发布 JW-FD/fits_600 读取；会覆盖修正版里同名活动区')
    parser.add_argument('--workers', type=int, default=None)
    args = parser.parse_args()
    if args.from_published and args.input:
        parser.error('--from-published 与 --input 不能同时用')
    src = get_path('fits_600_source') if args.from_published else args.input
    rotate_fits(skip_existing=args.skip_existing, skip_float64=args.skip_float64,
                max_workers=args.workers, input_folder=src, output_folder=args.output)
