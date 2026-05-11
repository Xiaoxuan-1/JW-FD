# -*- coding: utf-8 -*-
"""
步骤1: 从NOAA事件文件中提取耀斑标签（支持多年份数据）
输入: 多年份events文件夹 (2011-2024)
输出: flare_labels.csv (耀斑标签列表，包含完整时间信息)
格式: AR编号,开始时间,峰值时间,结束时间,耀斑等级
"""

import os
import re
import csv
from multiprocessing import Pool
from tqdm import tqdm
from config import PARAMS, get_path, get_events_folders
from utils import setup_logging

def parse_time(time_str):
    """解析时间字符串，处理////的情况"""
    if time_str == '////':
        return None
    return time_str

def process_single_event_file(file_path):
    """
    处理单个事件文件（worker函数）
    
    Args:
        file_path: 事件文件路径
    
    Returns:
        list: 该文件中提取的耀斑记录列表
    """
    results = []
    
    try:
        # 读取文件内容
        with open(file_path, 'r', encoding='utf-8') as file:
            lines = file.readlines()
        
        # 提取日期
        date_line = next((line for line in lines if line.startswith(':Date:')), None)
        if not date_line:
            return results
            
        date_str = date_line.split(':')[2].strip().replace(' ', '')
        
        # 提取含有XRA的行（X射线耀斑）
        xra_lines = [line.strip() for line in lines if 'XRA' in line]
        
        for line in xra_lines:
            # 分割行以提取各个字段
            parts = line.split()
            if len(parts) < 12:
                continue
            
            # 提取时间信息 (Begin, Max, End)
            try:
                begin_time = parse_time(parts[2])
                max_time = parse_time(parts[3])
                end_time = parse_time(parts[4])
                
                # 如果Max时间缺失，跳过
                if max_time is None:
                    continue
                
                # 如果Begin或End缺失，使用Max时间代替
                if begin_time is None:
                    begin_time = max_time
                if end_time is None:
                    end_time = max_time
                
            except (IndexError, ValueError):
                continue
            
            # 提取活动区域编号（最后一列）
            reg = parts[-1]
            
            # 检查reg是否为四位数字
            if not reg.isdigit() or len(reg) != 4:
                continue
            
            # 提取耀斑等级
            particulars = re.search(r'\b[C|M|X]\d\.\d\b', line)
            if not particulars:
                continue
                
            flare_class = particulars.group(0)
            ar_number = f'AR{reg}'
            
            # 格式化时间戳 (添加秒数00)
            begin_timestamp = f'{date_str}_{begin_time}00'
            max_timestamp = f'{date_str}_{max_time}00'
            end_timestamp = f'{date_str}_{end_time}00'
            
            # 保存为: [AR编号, 开始时间, 峰值时间, 结束时间, 耀斑等级]
            result = [ar_number, begin_timestamp, max_timestamp, end_timestamp, flare_class]
            results.append(result)
    
    except Exception as e:
        # 静默处理错误，返回空列表
        pass
    
    return results

def extract_flare_labels():
    """从事件文件中提取耀斑标签（支持多年份，支持多进程）"""
    logger = setup_logging('step1_flare_labels')
    logger.info("开始提取耀斑标签（多年份数据）...")
    
    # 获取所有年份的events文件夹
    events_folders = get_events_folders()
    
    if not events_folders:
        print("未找到任何events文件夹")
        logger.warning("未找到任何events文件夹")
        return
    
    print(f"找到 {len(events_folders)} 个年份的events数据:")
    for year, folder in events_folders:
        print(f"  {year}: {folder}")
        logger.info(f"  {year}: {folder}")
    
    # 收集所有事件文件
    event_files = []
    for year, folder_path in events_folders:
        for filename in sorted(os.listdir(folder_path)):
            if filename.endswith('.txt'):
                file_path = os.path.join(folder_path, filename)
                event_files.append(file_path)
    
    if not event_files:
        print("未找到事件文件")
        logger.warning("未找到事件文件")
        return
    
    print(f"\n总共找到 {len(event_files)} 个事件文件")
    logger.info(f"总共找到 {len(event_files)} 个事件文件")
    
    # 根据文件数量决定是否使用多进程
    use_multiprocess = PARAMS.get('use_multiprocess', True) and len(event_files) >= 100
    
    all_results = []
    
    if use_multiprocess:
        max_workers = min(PARAMS['max_workers'], len(event_files))
        print(f"使用 {max_workers} 个进程并行处理...")
        logger.info(f"使用 {max_workers} 个进程并行处理")
        
        with Pool(max_workers) as pool:
            results_list = list(tqdm(
                pool.imap_unordered(process_single_event_file, event_files),
                total=len(event_files),
                desc="提取耀斑标签"
            ))
        
        # 合并所有结果
        for results in results_list:
            all_results.extend(results)
    else:
        # 单进程处理
        print("使用单进程处理...")
        for file_path in tqdm(event_files, desc="提取耀斑标签"):
            results = process_single_event_file(file_path)
            all_results.extend(results)
    
    # 按峰值时间排序
    all_results.sort(key=lambda x: x[2])
    
    # 保存到CSV文件
    output_csv_path = get_path('flare_labels')
    with open(output_csv_path, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        # 写入表头
        writer.writerow(['AR_Number', 'Begin_Time', 'Max_Time', 'End_Time', 'Flare_Class'])
        # 写入数据
        writer.writerows(all_results)
    
    logger.info(f'提取完成，共{len(all_results)}条耀斑记录')
    logger.info(f'保存到: {output_csv_path}')
    print(f'\n步骤1完成: 提取了{len(all_results)}条耀斑标签')
    print(f'格式: AR编号, 开始时间, 峰值时间, 结束时间, 耀斑等级')
    print(f'保存到: {output_csv_path}')

if __name__ == '__main__':
    extract_flare_labels()
