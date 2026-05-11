# ⚠️ 必须在所有 import 之前设置！
import os
os.environ['TMPDIR'] = '/data/shaomf/tmp'
os.environ['TEMP'] = '/data/shaomf/tmp'
os.environ['TMP'] = '/data/shaomf/tmp'

# 确保目录存在
os.makedirs(os.environ['TMPDIR'], exist_ok=True)

# -*- coding: utf-8 -*-
"""
主流水线 - 太阳耀斑预测数据集构建流程

流程说明:
  Step 1: 从NOAA事件文件提取耀斑标签
  Step 2: 从HMI磁图裁剪活动区域 (600x600 FITS)
  Step 3: 将FITS转换为PNG图像
  Step 4: 从FITS提取特征生成数据集
  Step 5: 从PNG提取特征生成数据集
  Step 6: 生成活动区域演化视频
"""

import sys
import time
import pandas as pd
import numpy as np
from config import (
    PARAMS,
    OUTPUT_PATH,
    get_path,
    get_output_suffix,
    FLARE_LABEL_THRESHOLDS,
    get_prediction_hours_list,
)
from utils import setup_logging

def analyze_dataset():
    """分析生成的数据集"""
    suffix = get_output_suffix()
    csv_file_path = f"{OUTPUT_PATH}/solar_flare_dataset_png_{suffix}.csv"
    
    try:
        df = pd.read_csv(csv_file_path)
        
        print("=== 耀斑预测数据集分析报告 ===")
        print(f"数据集文件: {csv_file_path}")
        print(f"总记录数: {len(df)}")

        hours_list = get_prediction_hours_list()
        flare_label_cols = [
            f'flare_label_{thr}_{hr}hr'
            for hr in hours_list
            for thr in FLARE_LABEL_THRESHOLDS
        ]
        flare_class_cols = [f'flare_class_{hr}hr' for hr in hours_list]
        required_cols = flare_label_cols + flare_class_cols + ['image_filename', 'image_path']
        feature_cols = [col for col in df.columns if col not in required_cols]
        print(f"特征维度: {len(feature_cols)}")

        # 各 (阈值, 窗口) 正样本分布
        print(f"\n=== 各 flare_label 列正样本分布 ===")
        for col in flare_label_cols:
            if col not in df.columns:
                continue
            pos = (pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int) == 1).sum()
            print(f"{col}: 正样本 {pos} / {len(df)} ({pos/len(df)*100:.1f}%)")

        # 耀斑等级分布（以最长预测窗口的 flare_class 列为「有耀斑」子集）
        flare_class_main = flare_class_cols[-1]
        if flare_class_main not in df.columns:
            print(f"\n提示: 未找到列 {flare_class_main}，可能为旧版 CSV，跳过耀斑等级分布")
            flare_with_events = df.iloc[0:0]
        else:
            flare_with_events = df[df[flare_class_main].astype(str) != '0']
        if len(flare_with_events) > 0:
            print(f"\n=== 耀斑等级分布（基于 {flare_class_main}） ===")
            c_flares = flare_with_events[flare_with_events[flare_class_main].str.startswith('C', na=False)]
            m_flares = flare_with_events[flare_with_events[flare_class_main].str.startswith('M', na=False)]
            x_flares = flare_with_events[flare_with_events[flare_class_main].str.startswith('X', na=False)]
            
            print(f"C级耀斑: {len(c_flares)} ({len(c_flares)/len(flare_with_events)*100:.1f}%)")
            print(f"M级耀斑: {len(m_flares)} ({len(m_flares)/len(flare_with_events)*100:.1f}%)")
            print(f"X级耀斑: {len(x_flares)} ({len(x_flares)/len(flare_with_events)*100:.1f}%)")
        
        # 特征统计
        print(f"\n=== 特征统计 ===")
        print(f"特征数量: {len(feature_cols)}")
        print(f"缺失值总数: {df[feature_cols].isnull().sum().sum()}")
        
        # 活动区域统计
        image_names = df['image_filename'].str.replace('.png', '')
        ar_numbers = image_names.str.extract(r'(AR\d+)_\d{8}_\d{6}')[0]
        if not ar_numbers.empty:
            print(f"\n=== 活动区域统计 ===")
            print(f"活动区域数量: {ar_numbers.nunique()}")
        
        # 数据质量检查
        print(f"\n=== 数据质量检查 ===")
        print(f"重复记录: {df.duplicated().sum()}")
        
        numeric_features = df[feature_cols].select_dtypes(include=[np.number])
        if len(numeric_features.columns) > 0:
            Q1 = numeric_features.quantile(0.25)
            Q3 = numeric_features.quantile(0.75)
            IQR = Q3 - Q1
            outliers = ((numeric_features < (Q1 - 1.5 * IQR)) | (numeric_features > (Q3 + 1.5 * IQR))).sum().sum()
            total_values = len(numeric_features) * len(numeric_features.columns)
            outlier_ratio = (outliers / total_values) * 100
            print(f"潜在异常值: {outliers} / {total_values} ({outlier_ratio:.2f}%)")
            print(f"说明: 使用IQR方法检测，1-2%的异常值比例是正常的")
        
    except Exception as e:
        print(f"数据集分析失败: {e}")

def run_pipeline(start_step=1, end_step=6, skip_inspection=False):
    """
    运行数据处理流水线
    
    Args:
        start_step: 起始步骤 (1-6)
        end_step: 结束步骤 (1-6)
        skip_inspection: 是否跳过数据检测 (默认False)
    """
    logger = setup_logging('main_pipeline')
    
    steps = {
        1: ("提取耀斑标签", "step1_extract_flare_labels", "extract_flare_labels"),
        2: ("裁剪活动区域", "step2_crop_active_regions", "crop_active_regions"), 
        3: ("转换为PNG", "step3_convert_to_png", "convert_to_png"),
        4: ("生成FITS数据集", "step4_generate_dataset_fits", "generate_dataset"),
        5: ("生成PNG数据集", "step5_generate_dataset_png", "generate_dataset"),
        6: ("生成视频", "step6_make_movie", "make_all_movies")
    }
    
    print("=" * 60)
    print("  太阳耀斑预测数据集构建流水线")
    print("=" * 60)
    print(f"执行步骤: {start_step} → {end_step}")
    print(f"磁场阈值: {PARAMS['mag_threshold']} Gauss")
    print(f"预测窗口: {get_prediction_hours_list()} 小时")
    print(f"并行进程: {PARAMS['max_workers']}")
    print("=" * 60)
    print()
    
    # 数据完整性检测 (在流水线开始前执行)
    if not skip_inspection:
        print("\n【数据完整性检测】")
        print("-" * 50)
        print("提示: 运行 'python check_data_structure.py' 检查数据完整性")
        print()
        
        response = input("是否继续执行流水线? (y/n): ")
        if response.lower() != 'y':
            print("流水线执行取消")
            logger.info("用户取消流水线执行")
            return False
        print()
    
    total_start_time = time.time()
    
    for step_num in range(start_step, end_step + 1):
        if step_num not in steps:
            print(f"警告: 步骤 {step_num} 不存在")
            continue
        
        step_name, module_name, func_name = steps[step_num]
        print(f"【步骤 {step_num}】{step_name}")
        print("-" * 50)
        
        step_start_time = time.time()
        
        try:
            # 动态导入模块
            module = __import__(module_name)
            
            # 调用对应的主函数
            main_func = getattr(module, func_name, None)
            if main_func:
                main_func()
            else:
                print(f"错误: 模块 {module_name} 没有找到函数 {func_name}")
                continue
            
            step_time = time.time() - step_start_time
            print(f"✓ 步骤 {step_num} 完成，耗时: {step_time:.1f}秒")
            logger.info(f"步骤 {step_num} ({step_name}) 完成，耗时: {step_time:.1f}秒")
            
        except Exception as e:
            print(f"✗ 步骤 {step_num} 执行失败: {e}")
            logger.error(f"步骤 {step_num} ({step_name}) 执行失败: {e}")
            
            # 询问是否继续
            response = input("是否继续执行下一步骤? (y/n): ")
            if response.lower() != 'y':
                print("流水线执行中断")
                return False
        
        print()
    
    total_time = time.time() - total_start_time
    print("=" * 60)
    print("  流水线执行完成")
    print("=" * 60)
    print(f"总耗时: {total_time:.1f}秒 ({total_time/60:.1f}分钟)")
    logger.info(f"流水线执行完成，总耗时: {total_time:.1f}秒")
    
    # 运行数据集分析
    print("\n正在分析生成的数据集...")
    analyze_dataset()
    
    return True

def print_usage():
    """打印使用说明"""
    print("""
太阳耀斑预测数据集构建流水线
==============================

使用方法:
  python main_pipeline.py [start_step] [end_step] [--skip-inspection]

步骤说明:
  1. 提取耀斑标签    - 从NOAA事件文件提取耀斑记录
  2. 裁剪活动区域    - 从HMI磁图裁剪600x600区域
  3. 转换为PNG       - 将FITS转换为PNG图像
  4. 生成FITS数据集  - 从FITS提取29维特征
  5. 生成PNG数据集   - 从PNG提取29维特征
  6. 生成视频        - 生成活动区域演化MP4视频

数据检测:
  运行 'python check_data_structure.py' 检查数据完整性

选项:
  --skip-inspection  跳过数据完整性检测

示例:
  python main_pipeline.py                    # 执行所有步骤 (含数据检测)
  python main_pipeline.py --skip-inspection  # 执行所有步骤 (跳过检测)
  python main_pipeline.py 1 3                # 执行步骤 1 到 3
  python main_pipeline.py 4                  # 只执行步骤 4

配置文件: config.py
  - mag_threshold: 磁场归一化阈值 (200/500/1000)
  - prediction_hours: 耀斑预测窗口，int 或 list[int]（如 [1,3,6,12,24,48,72]），Step4/5 一次写入多列）
  - max_workers: 并行进程数
""")

if __name__ == "__main__":
    # 检查是否有 --skip-inspection 参数
    skip_inspection = '--skip-inspection' in sys.argv
    args = [arg for arg in sys.argv[1:] if arg != '--skip-inspection']
    
    if len(args) == 0:
        run_pipeline(skip_inspection=skip_inspection)
    elif len(args) == 1:
        if args[0] in ['-h', '--help']:
            print_usage()
        else:
            try:
                step = int(args[0])
                run_pipeline(step, step, skip_inspection=skip_inspection)
            except ValueError:
                print("错误: 步骤号必须是整数")
                print_usage()
    elif len(args) == 2:
        try:
            start_step = int(args[0])
            end_step = int(args[1])
            run_pipeline(start_step, end_step, skip_inspection=skip_inspection)
        except ValueError:
            print("错误: 步骤号必须是整数")
            print_usage()
    else:
        print("错误: 参数过多")
        print_usage()
