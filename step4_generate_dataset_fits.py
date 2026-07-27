# -*- coding: utf-8 -*-
"""
步骤4: 从FITS文件提取特征并生成数据集
输入: FITS文件 + 耀斑标签
输出: CSV数据集文件
"""

import argparse
import os
import gc
import csv
from astropy.io import fits
from datetime import datetime, timedelta
from multiprocessing import Pool, cpu_count
from tqdm import tqdm

from config import (
    PARAMS,
    FEATURE_NAMES,
    FLARE_LABEL_THRESHOLDS,
    OUTPUT_PATH,
    START_YEAR,
    END_YEAR,
    year_in_range,
    get_path,
    get_output_suffix,
    get_prediction_hours_list,
)
from utils import (
    setup_logging,
    compare_labels,
    label_meets_threshold,
    extract_year_from_filename,
    load_existing_csv_column,
)
from feature_extraction import extract_all_features

# 全局变量
_global_params = None

def init_worker(params):
    """初始化worker进程"""
    global _global_params
    _global_params = params

def load_flare_labels():
    """加载耀斑标签"""
    flare_records = []
    try:
        with open(get_path('flare_labels'), mode='r', newline='', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                flare_records.append({
                    'ar_number': row['AR_Number'],
                    'begin_time': row['Begin_Time'],
                    'max_time': row['Max_Time'],
                    'end_time': row['End_Time'],
                    'flare_class': row['Flare_Class']
                })
    except Exception as e:
        print(f"加载耀斑标签失败: {e}")
    return flare_records

def get_flare_label(image_filename, flare_records, prediction_hours_list):
    """严格预测：每个 hr 为半开区间 [Begin-hr, Begin)；Begin-hr 含、Begin 不含；t>=Begin 不正样本。"""
    base_name = image_filename.replace('.fits', '')
    parts = base_name.split('_')
    n_hours = len(prediction_hours_list)
    n_thresh = len(FLARE_LABEL_THRESHOLDS)
    empty_labels = ['0'] * (n_thresh * n_hours)
    empty_classes = ['0'] * n_hours
    if len(parts) < 3:
        return empty_labels, empty_classes

    txt_ARnum = parts[0]
    try:
        txt_datetime = datetime.strptime(parts[1] + parts[2], "%Y%m%d%H%M%S")
    except ValueError:
        return empty_labels, empty_classes

    best_per_window = {hr: '0' for hr in prediction_hours_list}
    max_hours = max(prediction_hours_list)

    for record in flare_records:
        if txt_ARnum != record['ar_number']:
            continue
        try:
            begin_datetime = datetime.strptime(record['begin_time'], "%Y%m%d_%H%M%S")
        except ValueError:
            continue
        # 早退：用最大窗口快速过滤（仅爆发前 [Begin-max_h, Begin)）
        if not (begin_datetime - timedelta(hours=max_hours) <= txt_datetime < begin_datetime):
            continue
        for hr in prediction_hours_list:
            if begin_datetime - timedelta(hours=hr) <= txt_datetime < begin_datetime:
                if compare_labels(record['flare_class'], best_per_window[hr]):
                    best_per_window[hr] = record['flare_class']

    flare_labels = []
    flare_classes = []
    for hr in prediction_hours_list:
        b = best_per_window[hr]
        for thr in FLARE_LABEL_THRESHOLDS:
            flare_labels.append(label_meets_threshold(b, thr))
        flare_classes.append(str(b))
    return flare_labels, flare_classes

def process_batch(batch):
    """批量处理多个FITS文件 - 先预加载到内存再处理"""
    global _global_params
    flare_records = _global_params['flare_records']
    prediction_hours_list = _global_params['prediction_hours_list']
    logger = setup_logging('step4_generate_dataset_fits')
    
    # 第一步：预加载所有文件到内存
    preloaded = []
    for fits_path in batch:
        try:
            # 捕获astropy的警告并记录文件名
            import warnings
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                with fits.open(fits_path, memmap=False) as hdul:
                    data = hdul[0].data.copy()
                    preloaded.append((fits_path, data))
                
                # 检查是否有截断警告
                for warning in w:
                    if "truncated" in str(warning.message):
                        logger.warning(f"FITS文件截断: {fits_path} - {warning.message}")
                        
        except Exception as e:
            preloaded.append((fits_path, None, str(e)))
    
    # 第二步：从内存处理
    results = []
    failed_files = []
    
    for item in preloaded:
        if len(item) == 3:  # 加载失败
            failed_files.append((item[0], item[2]))
            continue
        
        fits_path, magnetogram = item
        try:
            # 检查数据是否为空或异常
            if magnetogram is None or magnetogram.size == 0:
                failed_files.append((fits_path, "空数据或数据异常"))
                continue
            
            # 捕获numpy警告并记录
            import warnings
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                features = extract_all_features(magnetogram)
                
                # 记录numpy计算警告
                for warning in w:
                    if "Mean of empty slice" in str(warning.message) or "Degrees of freedom" in str(warning.message):
                        logger.warning(f"特征提取警告: {fits_path} - {warning.message}")
            
            image_filename = os.path.basename(fits_path)
            flare_labels, flare_classes = get_flare_label(
                image_filename, flare_records, prediction_hours_list
            )

            ar_num = image_filename.split('_')[0].replace('AR', '')
            image_path = f"./{ar_num}/{image_filename}"

            feature_values = [f"{x:.3f}" for x in features]
            results.append(feature_values + flare_labels + flare_classes + [image_filename, image_path])
        except Exception as e:
            failed_files.append((fits_path, str(e)))
    
    del preloaded
    gc.collect()
    return results, failed_files

def build_csv_headers(prediction_hours_list):
    flare_label_cols = [
        f'flare_label_{thr}_{hr}hr'
        for hr in prediction_hours_list
        for thr in FLARE_LABEL_THRESHOLDS
    ]
    flare_class_cols = [f'flare_class_{hr}hr' for hr in prediction_hours_list]
    return FEATURE_NAMES + flare_label_cols + flare_class_cols + ['image_filename', 'image_path']


def generate_dataset(skip_existing=False):
    """主函数：提取特征并生成数据集"""
    logger = setup_logging('step4_generate_dataset_fits')
    logger.info("开始生成FITS数据集...")

    fits_folder = get_path('fits_600')
    suffix = get_output_suffix()
    output_csv = f"{OUTPUT_PATH}/solar_flare_dataset_fits_{suffix}.csv"

    logger.info(f"参数配置: {suffix}")
    logger.info(f"输出文件: {output_csv}")
    if skip_existing:
        logger.info("增量模式: 仅处理 CSV 中缺失的 FITS，追加写入")
        print("增量模式: 仅处理 CSV 中缺失的 FITS，追加写入")

    flare_records = load_flare_labels()
    logger.info(f"加载了{len(flare_records)}个耀斑标签")

    fits_files = []
    for root, dirs, files in os.walk(fits_folder):
        for file in files:
            if file.endswith('.fits'):
                fits_files.append(os.path.join(root, file))

    fits_files.sort()
    total_before = len(fits_files)
    fits_files = [f for f in fits_files if year_in_range(extract_year_from_filename(f))]
    filter_msg = f"年份过滤 [{START_YEAR}, {END_YEAR}]：{total_before} -> {len(fits_files)}"
    logger.info(filter_msg)
    print(filter_msg)

    skipped_csv = 0
    if skip_existing:
        existing_names = load_existing_csv_column(output_csv, 'image_filename')
        if existing_names:
            to_process = []
            for fits_path in fits_files:
                if os.path.basename(fits_path) in existing_names:
                    skipped_csv += 1
                else:
                    to_process.append(fits_path)
            skip_msg = f"CSV 已有 {len(existing_names)} 条，跳过 {skipped_csv}，待处理 {len(to_process)}"
            logger.info(skip_msg)
            print(skip_msg)
            fits_files = to_process

    logger.info(f"找到{len(fits_files)}个FITS文件待处理")
    print(f"找到 {len(fits_files)} 个FITS文件待处理")

    prediction_hours_list = get_prediction_hours_list()
    headers = build_csv_headers(prediction_hours_list)

    if not fits_files:
        print(f"步骤4完成: 无需追加 (CSV 跳过 {skipped_csv} 条)")
        return {'appended': 0, 'skipped': skipped_csv, 'failed': 0, 'output_csv': output_csv}

    logger.info(f"预测窗口(小时): {prediction_hours_list}")
    print(f"预测窗口(小时): {prediction_hours_list}")

    params = {
        'flare_records': flare_records,
        'prediction_hours_list': prediction_hours_list,
    }

    all_results = []
    all_failed = []

    if PARAMS['use_multiprocess']:
        max_workers = PARAMS['max_workers'] or cpu_count()
        batch_size = PARAMS.get('preload_count', 20)

        batches = [fits_files[i:i+batch_size] for i in range(0, len(fits_files), batch_size)]
        print(f"使用 {max_workers} 个进程，每批 {batch_size} 个文件")

        with Pool(max_workers, initializer=init_worker, initargs=(params,)) as pool:
            for results, failed_files in tqdm(pool.imap_unordered(process_batch, batches),
                                              total=len(batches), desc="提取FITS特征"):
                all_results.extend(results)
                all_failed.extend(failed_files)
    else:
        init_worker(params)
        for fits_file in tqdm(fits_files, desc="提取FITS特征"):
            results, failed = process_batch([fits_file])
            all_results.extend(results)
            all_failed.extend(failed)

    if all_failed:
        logger.warning(f"共有 {len(all_failed)} 个文件处理失败:")
        for failed_file, error in all_failed:
            logger.error(f"  失败文件: {failed_file}, 错误: {error}")
        print(f"警告: {len(all_failed)} 个文件处理失败，详见日志")

    logger.info(f"有效结果: {len(all_results)}/{len(fits_files)}")

    append_mode = skip_existing and os.path.exists(output_csv) and os.path.getsize(output_csv) > 0
    if skip_existing:
        all_results.sort(key=lambda x: x[-2])
        write_header = not os.path.exists(output_csv) or os.path.getsize(output_csv) == 0
        mode = 'w' if write_header else 'a'
        with open(output_csv, mode=mode, newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            if write_header:
                writer.writerow(headers)
            writer.writerows(all_results)
    else:
        all_results.sort(key=lambda x: x[-2])
        with open(output_csv, mode='w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(headers)
            writer.writerows(all_results)

    logger.info(f"FITS数据集已保存到: {output_csv}")
    action = "追加" if append_mode else "写入"
    print(f"步骤4完成: {action} {len(all_results)} 条记录 (CSV 跳过 {skipped_csv} 条)")
    print(f"数据集文件: {output_csv}")
    return {
        'appended': len(all_results),
        'skipped': skipped_csv,
        'failed': len(all_failed),
        'output_csv': output_csv,
    }

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Step4: 从 FITS 生成数据集 CSV')
    parser.add_argument(
        '--skip-existing',
        action='store_true',
        help='仅处理 CSV 中缺失的 FITS，追加到文件末尾',
    )
    args = parser.parse_args()
    generate_dataset(skip_existing=args.skip_existing)
