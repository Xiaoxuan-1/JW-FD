# -*- coding: utf-8 -*-
"""
按活动区 (AR) 划分 train/val/test。

官方划分：分层拒绝采样，seed=3970。
每个 NOAA 区落入一个耀斑产能层（multiple X / single X / M5-not-X /
M1-not-M5 / C-only / quiet），层内够大时再按过日面帧数三分位；
候选种子须同时满足：val/test 各至少 5 个 X 与 5 个 M5 正样本区、
24 h 正帧比在 [0.5, 2]、单区不超过该子集正帧的 25%、
unsigned-flux 与 NL-length 的 val–test Cohen d < 0.30。

冻结的 AR 成员名单见 ``split_v2_ar_membership.json``。
默认 ``split_csv`` 读取该名单。
"""

import argparse
import csv
import json
import os
import random
import re
import time
from collections import defaultdict
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
OFFICIAL_SPLIT_SEED = 3970
OFFICIAL_SPLIT_CHECKSUM = "34781b5227c55284"
DEFAULT_AR_MEMBERSHIP = os.path.join(_HERE, "split_v2_ar_membership.json")


def load_ar_membership(path=None):
    """读取冻结的 seed=3970 AR 成员名单，返回 {ar_id: split}。"""
    path = path or DEFAULT_AR_MEMBERSHIP
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assign = {}
    for split in ("train", "val", "test"):
        for ar_id in data.get(split, []):
            assign[str(ar_id)] = split
    return assign, data


def apply_ar_membership(ar_data_map, assign):
    """按冻结名单把已解析的 AR 分到 train/val/test。"""
    train_ars, val_ars, test_ars, leftover = [], [], [], []
    for ar_id in ar_data_map:
        split = assign.get(str(ar_id))
        if split == "train":
            train_ars.append(ar_id)
        elif split == "val":
            val_ars.append(ar_id)
        elif split == "test":
            test_ars.append(ar_id)
        else:
            leftover.append(ar_id)
    split_info = {
        "official": {
            "seed": OFFICIAL_SPLIT_SEED,
            "checksum": OFFICIAL_SPLIT_CHECKSUM,
            "total": len(ar_data_map),
            "train": len(train_ars),
            "val": len(val_ars),
            "test": len(test_ars),
            "leftover": leftover,
            "train_ars": sorted(train_ars),
            "val_ars": sorted(val_ars),
            "test_ars": sorted(test_ars),
        }
    }
    return train_ars, val_ars, test_ars, split_info


def extract_ar_id(filename):
    if not filename:
        return None
    match = re.search(r'AR(\d+)', filename)
    if match:
        return match.group(1)
    return None


def get_flare_category(flare_class_str):
    if not flare_class_str:
        return '0'
    flare_class_str = flare_class_str.strip()
    if flare_class_str.startswith('X'):
        return 'X'
    if flare_class_str.startswith('M'):
        return 'M'
    if flare_class_str.startswith('C'):
        return 'C'
    return '0'


def get_priority(level):
    priority_map = {'X': 4, 'M': 3, 'C': 2, '0': 1}
    return priority_map.get(level, 0)


def get_output_prefix(input_file):
    """返回与输入 CSV 同目录、不含 .csv 后缀的路径前缀。"""
    input_file = os.path.abspath(input_file)
    dir_name = os.path.dirname(input_file)
    base_name = os.path.basename(input_file)
    if base_name.endswith('.csv'):
        stem = base_name[:-4]
    else:
        stem = base_name
    return os.path.join(dir_name, stem)


def load_and_group_data(file_paths):
    ar_data_map = defaultdict(list)
    ar_max_label = {}
    header = None
    total_rows = 0
    error_rows = 0
    file_stats = {}

    for file_path in file_paths:
        if not os.path.exists(file_path):
            file_stats[file_path] = {'rows': 0, 'errors': 0, 'exists': False}
            continue

        file_rows = 0
        file_errors = 0

        with open(file_path, 'r', encoding='utf-8', errors='ignore', newline='') as f:
            reader = csv.reader(f)

            for idx, row in enumerate(reader):
                if idx == 0:
                    if header is None:
                        header = row
                    continue

                if len(row) < 3:
                    file_errors += 1
                    continue

                file_rows += 1
                total_rows += 1

                try:
                    flare_class_raw = row[-3]
                    image_filename = row[-2]
                    ar_id = extract_ar_id(image_filename)
                    if not ar_id:
                        file_errors += 1
                        continue

                    current_level = get_flare_category(flare_class_raw)
                    row_with_source = row + [file_path]
                    ar_data_map[ar_id].append(row_with_source)

                    if ar_id not in ar_max_label:
                        ar_max_label[ar_id] = current_level
                    elif get_priority(current_level) > get_priority(ar_max_label[ar_id]):
                        ar_max_label[ar_id] = current_level
                except Exception:
                    file_errors += 1
                    error_rows += 1

        file_stats[file_path] = {
            'rows': file_rows,
            'errors': file_errors,
            'exists': True,
        }

    return header, ar_data_map, ar_max_label, total_rows, error_rows, file_stats


def stratified_split_ars(ar_max_label, train_r, val_r, test_r):
    grouped_ars = {'X': [], 'M': [], 'C': [], '0': []}

    for ar_id, level in ar_max_label.items():
        grouped_ars.get(level, grouped_ars['0']).append(ar_id)

    train_ars = []
    val_ars = []
    test_ars = []
    split_info = {}

    for level, ar_list in grouped_ars.items():
        random.shuffle(ar_list)
        count = len(ar_list)
        train_end = int(count * train_r)
        val_end = int(count * (train_r + val_r))

        if count == 1:
            t_list, v_list, te_list = ar_list, [], []
        elif count == 2:
            t_list, v_list, te_list = ar_list[:1], ar_list[1:2], []
        else:
            t_list = ar_list[:train_end]
            v_list = ar_list[train_end:val_end]
            te_list = ar_list[val_end:]

        train_ars.extend(t_list)
        val_ars.extend(v_list)
        test_ars.extend(te_list)

        split_info[level] = {
            'total': count,
            'train': len(t_list),
            'val': len(v_list),
            'test': len(te_list),
            'train_ars': sorted(t_list),
            'val_ars': sorted(v_list),
            'test_ars': sorted(te_list),
        }

    return train_ars, val_ars, test_ars, split_info


def calculate_sample_stats(ar_data_map, train_ars, val_ars, test_ars):
    sample_stats = {
        level: {'total': 0, 'train': 0, 'val': 0, 'test': 0}
        for level in ['X', 'M', 'C', '0']
    }

    train_set = set(train_ars)
    val_set = set(val_ars)
    test_set = set(test_ars)

    for ar_id, rows in ar_data_map.items():
        if ar_id in train_set:
            split = 'train'
        elif ar_id in val_set:
            split = 'val'
        elif ar_id in test_set:
            split = 'test'
        else:
            continue

        for row in rows:
            flare_class_raw = row[-4]
            level = get_flare_category(flare_class_raw)
            sample_stats[level]['total'] += 1
            sample_stats[level][split] += 1

    return sample_stats


def write_split_csv_by_file(header, ar_data_map, ar_ids, output_path, source_file=None):
    with open(output_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        if header:
            writer.writerow(header)

        count = 0
        for ar_id in ar_ids:
            if ar_id not in ar_data_map:
                continue
            for row in ar_data_map[ar_id]:
                if source_file and row[-1] != source_file:
                    continue
                writer.writerow(row[:-1])
                count += 1
    return count


def generate_log(log_path, stats):
    with open(log_path, 'w', encoding='utf-8') as f:
        f.write("=" * 100 + "\n")
        f.write(" " * 30 + "数据集分割统计日志\n")
        f.write("=" * 100 + "\n")
        f.write(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"随机种子：{stats['random_seed']} (确保重复运行结果一致)\n")
        f.write(
            f"分割比例：Train:{stats['ratio'][0]*100:.0f}%, "
            f"Val:{stats['ratio'][1]*100:.0f}%, Test:{stats['ratio'][2]*100:.0f}%\n"
        )
        f.write("\n")

        f.write("-" * 100 + "\n")
        f.write("【输入文件统计】\n")
        f.write("-" * 100 + "\n")
        for file_path, file_stat in stats['file_stats'].items():
            f.write(f"文件：{os.path.basename(file_path)}\n")
            f.write(f"  状态：{'✓ 存在' if file_stat['exists'] else '✗ 不存在'}\n")
            f.write(f"  有效行数：{file_stat['rows']}\n")
            f.write(f"  解析错误：{file_stat['errors']}\n")
            f.write("\n")

        f.write("-" * 100 + "\n")
        f.write("【总体统计】\n")
        f.write("-" * 100 + "\n")
        f.write(f"有效数据总行数：{stats['total_rows']}\n")
        f.write(f"独立活动区 (AR) 总数：{stats['total_ars']}\n")
        f.write(f"解析异常行数：{stats['error_rows']}\n")
        f.write("\n")

        sample_stats = stats.get('sample_stats', {})
        f.write("-" * 100 + "\n")
        f.write("【实际样本（行数）等级分布及分割详情】\n")
        f.write("-" * 100 + "\n")
        f.write(
            f"{'等级':<6} | {'总数':<8} | {'训练集':<8} | {'验证集':<8} | "
            f"{'测试集':<8} | {'训练比例':<10} | {'验证比例':<10} | {'测试比例':<10}\n"
        )
        f.write("-" * 100 + "\n")

        for level in ['X', 'M', 'C', '0']:
            info = sample_stats.get(level, {'total': 0, 'train': 0, 'val': 0, 'test': 0})
            total = info['total']
            train = info['train']
            val = info['val']
            test = info['test']
            ratio_train = (train / total * 100) if total > 0 else 0
            ratio_val = (val / total * 100) if total > 0 else 0
            ratio_test = (test / total * 100) if total > 0 else 0
            f.write(
                f"{level:<6} | {total:<8} | {train:<8} | {val:<8} | {test:<8} | "
                f"{ratio_train:.2f}% | {ratio_val:.2f}% | {ratio_test:.2f}%\n"
            )

        f.write("-" * 100 + "\n")
        f.write("【分割验证】\n")
        f.write("-" * 100 + "\n")
        total_output_rows = sum(
            info['rows']['train'] + info['rows']['val'] + info['rows']['test']
            for info in stats['output_files_info']
        )
        f.write(f"输入总行数：{stats['total_rows']}\n")
        f.write(f"输出总行数：{total_output_rows}\n")
        if total_output_rows == stats['total_rows']:
            f.write("✅ 验证：输出行数与输入行数一致\n")
        else:
            f.write(
                f"⚠️  验证：输出行数与输入行数不一致 "
                f"(差值：{abs(total_output_rows - stats['total_rows'])})\n"
            )


def split_csv(
    input_csv,
    train_ratio=0.8,
    val_ratio=0.1,
    test_ratio=0.1,
    seed=OFFICIAL_SPLIT_SEED,
    log_path=None,
    ar_membership=DEFAULT_AR_MEMBERSHIP,
):
    """
    对单个 CSV 按 AR 划分 train/val/test，输出与输入同目录。

    默认读取 ``split_v2_ar_membership.json``（seed=3970 官方名单）。
    传入 ``ar_membership=None`` 时退回 X/M/C/0 分层 shuffle（非官方）。

    Returns:
        dict: 分割统计与输出文件路径
    """
    input_csv = os.path.abspath(input_csv)
    if not os.path.exists(input_csv):
        raise FileNotFoundError(f"输入文件不存在: {input_csv}")

    random.seed(seed)
    start_time = time.time()

    header, ar_data_map, ar_max_label, total_rows, error_rows, file_stats = load_and_group_data(
        [input_csv]
    )
    total_ars = len(ar_data_map)
    if total_ars == 0:
        raise ValueError(f"未解析到有效活动区数据: {input_csv}")

    if ar_membership:
        if not os.path.exists(ar_membership):
            raise FileNotFoundError(f"官方 AR 名单不存在: {ar_membership}")
        assign, _meta = load_ar_membership(ar_membership)
        train_ars, val_ars, test_ars, split_info = apply_ar_membership(
            ar_data_map, assign
        )
        leftover = split_info["official"]["leftover"]
        if leftover:
            print(
                f"警告: {len(leftover)} 个 AR 不在 seed=3970 名单中，已排除: "
                f"{leftover[:12]}{'...' if len(leftover) > 12 else ''}"
            )
    else:
        train_ars, val_ars, test_ars, split_info = stratified_split_ars(
            ar_max_label, train_ratio, val_ratio, test_ratio
        )
    sample_stats = calculate_sample_stats(ar_data_map, train_ars, val_ars, test_ars)

    output_prefix = get_output_prefix(input_csv)
    train_file = f"{output_prefix}_train.csv"
    val_file = f"{output_prefix}_val.csv"
    test_file = f"{output_prefix}_test.csv"

    train_count = write_split_csv_by_file(header, ar_data_map, train_ars, train_file, input_csv)
    val_count = write_split_csv_by_file(header, ar_data_map, val_ars, val_file, input_csv)
    test_count = write_split_csv_by_file(header, ar_data_map, test_ars, test_file, input_csv)

    output_files_info = [{
        'source': os.path.basename(input_csv),
        'train': train_file,
        'val': val_file,
        'test': test_file,
        'rows': {'train': train_count, 'val': val_count, 'test': test_count},
    }]

    if log_path is None:
        log_path = f"{output_prefix}_split_log.txt"

    stats = {
        'input_files': [input_csv],
        'random_seed': seed,
        'ratio': [train_ratio, val_ratio, test_ratio],
        'total_rows': total_rows,
        'total_ars': total_ars,
        'error_rows': error_rows,
        'split_info': split_info,
        'train_ars': len(train_ars),
        'val_ars': len(val_ars),
        'test_ars': len(test_ars),
        'file_stats': file_stats,
        'output_files_info': output_files_info,
        'sample_stats': sample_stats,
        'duration_sec': time.time() - start_time,
    }
    generate_log(log_path, stats)

    return {
        'total_rows': total_rows,
        'train_file': train_file,
        'val_file': val_file,
        'test_file': test_file,
        'train_count': train_count,
        'val_count': val_count,
        'test_count': test_count,
        'log_path': log_path,
        'duration_sec': stats['duration_sec'],
    }


def main():
    parser = argparse.ArgumentParser(
        description="按 AR 划分 train/val/test（默认 seed=3970 官方名单）"
    )
    parser.add_argument('--input', required=True, help='输入 CSV 路径')
    parser.add_argument('--train-ratio', type=float, default=0.8)
    parser.add_argument('--val-ratio', type=float, default=0.1)
    parser.add_argument('--test-ratio', type=float, default=0.1)
    parser.add_argument(
        '--seed',
        type=int,
        default=OFFICIAL_SPLIT_SEED,
        help=f'仅在 --no-ar-list 时生效；官方划分为 {OFFICIAL_SPLIT_SEED}',
    )
    parser.add_argument('--log', default=None, help='分割日志输出路径')
    parser.add_argument(
        '--ar-list',
        default=DEFAULT_AR_MEMBERSHIP,
        help='官方 AR 成员 JSON（默认 split_v2_ar_membership.json）',
    )
    parser.add_argument(
        '--no-ar-list',
        action='store_true',
        help='不用官方名单，退回 X/M/C/0 分层 shuffle（非论文官方划分）',
    )
    args = parser.parse_args()

    result = split_csv(
        args.input,
        train_ratio=args.train_ratio,
        val_ratio=args.val_ratio,
        test_ratio=args.test_ratio,
        seed=args.seed,
        log_path=args.log,
        ar_membership=None if args.no_ar_list else args.ar_list,
    )

    print(f"分割完成: {result['total_rows']} 行")
    print(f"  train: {result['train_count']} -> {result['train_file']}")
    print(f"  val:   {result['val_count']} -> {result['val_file']}")
    print(f"  test:  {result['test_count']} -> {result['test_file']}")
    print(f"  log:   {result['log_path']}")


if __name__ == '__main__':
    main()
