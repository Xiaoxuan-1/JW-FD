# -*- coding: utf-8 -*-
"""
步骤 1: 从 NOAA/SWPC 事件表提取耀斑标签。

解析与发布目录相同：`+` 只表示关联报告，不决定是否保留；时间可带 B/A/U
前缀或为 ////；跨年重复的事件文件按开始时间、等级、区号和观测站去重。
C1.0 及以上写入 flare_labels.csv。`label_corrections.csv` 里的两次活动区
归属在写出前套用，避免按 SWPC 原文重跑又改回去。
"""

import csv
import os

import pandas as pd

from config import END_YEAR, get_path
from goes_events import load_xra
from utils import setup_logging

# 磁图从 2011 年开始。耀斑表从 2010 年开始，与已发布的 flare_labels.csv 一致。
CATALOG_START_YEAR = 2010
CORRECTIONS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'label_corrections.csv')
COLUMNS = [
    'AR_Number', 'Begin_Time', 'Max_Time', 'End_Time', 'Flare_Class',
    'Event', 'Plus', 'Obs', 'Begin_Qualifier', 'Begin_From', 'Source',
]


def _fmt(t) -> str:
    return '' if pd.isna(t) else t.strftime('%Y%m%d_%H%M%S')


def apply_corrections(frame: pd.DataFrame, path: str = CORRECTIONS) -> pd.DataFrame:
    """把修正表里的区号套到唯一匹配的事件上。匹配不到或多于一条就停止。"""
    corrections = pd.read_csv(path, dtype=str)
    out = frame.copy()
    for row in corrections.itertuples(index=False):
        mask = (
            (out['Begin_Time'] == row.Begin_Time)
            & (out['Event'].astype(str) == str(row.Event))
            & (out['Flare_Class'] == row.Flare_Class)
            & (out['AR_Number'] == row.Old_AR)
        )
        # 重复运行时这一行已经是新区号，按新区号再认一次。
        already = (
            (out['Begin_Time'] == row.Begin_Time)
            & (out['Event'].astype(str) == str(row.Event))
            & (out['Flare_Class'] == row.Flare_Class)
            & (out['AR_Number'] == row.New_AR)
        )
        n_old, n_new = int(mask.sum()), int(already.sum())
        if n_old == 1 and n_new == 0:
            out.loc[mask, 'AR_Number'] = row.New_AR
        elif n_old == 0 and n_new == 1:
            continue
        else:
            raise RuntimeError(
                f'{row.Begin_Time} 事件 {row.Event} 匹配到 {n_old} 条旧区号、{n_new} 条新区号'
            )
    return out


def build_catalog(labels_root: str) -> pd.DataFrame:
    years = range(CATALOG_START_YEAR, END_YEAR + 1)
    raw, stats = load_xra(labels_root, years)
    if stats['unparsed_lines']:
        raise RuntimeError(f'{stats["unparsed_lines"]} 行 XRA 没有解析出来')
    raw = raw[raw['flux_cls'] >= 1e-6].copy()
    frame = pd.DataFrame({
        'AR_Number': raw['reg'].map(lambda r: f'AR{r}' if r else ''),
        'Begin_Time': raw['begin'].map(_fmt),
        'Max_Time': raw['max'].map(_fmt),
        'End_Time': raw['end'].map(_fmt),
        'Flare_Class': raw['cls'],
        'Event': raw['event'].astype(int).astype(str),
        'Plus': raw['plus'].astype(int).astype(str),
        'Obs': raw['obs'],
        'Begin_Qualifier': raw['begin_qualifier'],
        'Begin_From': raw['begin_from'],
        'Source': raw['source'],
    })
    return apply_corrections(frame)


def extract_flare_labels(skip_existing=False):
    """写出 flare_labels.csv。skip_existing 时不重读事件表，只套用修正表。"""
    logger = setup_logging('step1_flare_labels')
    output_csv_path = get_path('flare_labels')
    if skip_existing and os.path.exists(output_csv_path):
        logger.info('增量模式: 保留已有记录，只套用活动区修正')
        print('增量模式: 保留已有记录，只套用活动区修正')
        existing = pd.read_csv(output_csv_path, dtype=str).fillna('')
        corrected = apply_corrections(existing)
        _write(corrected, output_csv_path)
        print(f'步骤1完成: {len(corrected)} 条，已套用 label_corrections.csv')
        return {'total': len(corrected), 'output_csv': output_csv_path}

    logger.info('从 SWPC 事件表重建耀斑目录')
    print('从 SWPC 事件表重建耀斑目录')
    frame = build_catalog(get_path('labels_root'))
    _write(frame, output_csv_path)
    logger.info(f'提取完成，共 {len(frame)} 条，保存到 {output_csv_path}')
    print(f'步骤1完成: {len(frame)} 条耀斑标签')
    print(f'保存到: {output_csv_path}')
    return {'total': len(frame), 'output_csv': output_csv_path}


def _write(frame: pd.DataFrame, path: str) -> None:
    frame.to_csv(path, index=False, columns=COLUMNS, lineterminator='\n')


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Step1: 从 NOAA events 提取耀斑标签')
    parser.add_argument(
        '--skip-existing',
        action='store_true',
        help='保留已有 flare_labels.csv，只套用 label_corrections.csv',
    )
    parser.add_argument(
        '--output',
        default='',
        help='写到这个路径，而不是 config 里的 flare_labels.csv',
    )
    args = parser.parse_args()
    if args.output:
        _write(build_catalog(get_path('labels_root')), args.output)
        print(f'保存到: {args.output}')
    else:
        extract_flare_labels(skip_existing=args.skip_existing)
