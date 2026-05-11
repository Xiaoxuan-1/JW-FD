# ⚠️ 必须在所有 import 之前设置！
import os
os.environ['TMPDIR'] = '/data/shaomf/tmp'
os.environ['TEMP'] = '/data/shaomf/tmp'
os.environ['TMP'] = '/data/shaomf/tmp'

# 确保目录存在
os.makedirs(os.environ['TMPDIR'], exist_ok=True)


# -*- coding: utf-8 -*-
"""
无交互流水线 - 太阳耀斑预测数据集构建流程（适用于nohup后台运行）

流程说明:
  Step 1: 从NOAA事件文件提取耀斑标签
  Step 2: 从HMI磁图裁剪活动区域 (600x600 FITS)
  Step 3: 将FITS转换为PNG图像
  Step 4: 从FITS提取特征生成数据集
  Step 5: 从PNG提取特征生成数据集
  Step 6: 生成活动区域演化视频

使用方法:
  python run_pipeline.py                    # 执行所有步骤
  python run_pipeline.py 1 3                # 执行步骤 1 到 3
  python run_pipeline.py 4                  # 只执行步骤 4
  
后台运行:
  nohup python run_pipeline.py > pipeline.log 2>&1 &
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

def run_pipeline_no_interaction(start_step=1, end_step=6):
    """
    运行数据处理流水线（无交互版本）
    
    Args:
        start_step: 起始步骤 (1-6)
        end_step: 结束步骤 (1-6)
    
    Returns:
        bool: 是否成功完成
    """
    logger = setup_logging('run_pipeline')
    
    steps = {
        1: ("提取耀斑标签", "step1_extract_flare_labels", "extract_flare_labels"),
        2: ("裁剪活动区域", "step2_crop_active_regions", "crop_active_regions"), 
        3: ("转换为PNG", "step3_convert_to_png", "convert_to_png"),
        4: ("生成FITS数据集", "step4_generate_dataset_fits", "generate_dataset"),
        5: ("生成PNG数据集", "step5_generate_dataset_png", "generate_dataset"),
        6: ("生成视频", "step6_make_movie", "make_all_movies")
    }
    
    print("=" * 60)
    print("  太阳耀斑预测数据集构建流水线（无交互模式）")
    print("=" * 60)
    print(f"执行步骤: {start_step} → {end_step}")
    print(f"磁场阈值: {PARAMS['mag_threshold']} Gauss")
    print(f"预测窗口: {get_prediction_hours_list()} 小时")
    print(f"并行进程: {PARAMS['max_workers']}")
    print(f"开始时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    print()
    
    logger.info("=" * 60)
    logger.info("流水线开始执行（无交互模式）")
    logger.info(f"执行步骤: {start_step} → {end_step}")
    logger.info(f"磁场阈值: {PARAMS['mag_threshold']} Gauss")
    logger.info(f"预测窗口: {get_prediction_hours_list()} 小时")
    logger.info(f"并行进程: {PARAMS['max_workers']}")
    logger.info("=" * 60)
    
    total_start_time = time.time()
    failed_steps = []
    
    for step_num in range(start_step, end_step + 1):
        if step_num not in steps:
            print(f"警告: 步骤 {step_num} 不存在")
            logger.warning(f"步骤 {step_num} 不存在")
            continue
        
        step_name, module_name, func_name = steps[step_num]
        print(f"\n【步骤 {step_num}】{step_name}")
        print("-" * 50)
        logger.info(f"开始执行步骤 {step_num}: {step_name}")
        
        step_start_time = time.time()
        
        try:
            # 动态导入模块
            print(f"正在导入模块: {module_name}")
            logger.info(f"正在导入模块: {module_name}")
            module = __import__(module_name)
            
            # 调用对应的主函数
            print(f"正在调用函数: {func_name}")
            logger.info(f"正在调用函数: {func_name}")
            main_func = getattr(module, func_name, None)
            if main_func:
                main_func()
            else:
                error_msg = f"错误: 模块 {module_name} 没有找到函数 {func_name}"
                print(error_msg)
                logger.error(error_msg)
                failed_steps.append((step_num, step_name, error_msg))
                continue
            
            step_time = time.time() - step_start_time
            print(f"✓ 步骤 {step_num} 完成，耗时: {step_time:.1f}秒 ({step_time/60:.1f}分钟)")
            logger.info(f"步骤 {step_num} ({step_name}) 完成，耗时: {step_time:.1f}秒")
            
        except Exception as e:
            step_time = time.time() - step_start_time
            error_msg = f"步骤 {step_num} 执行失败: {e}"
            print(f"✗ {error_msg}")
            print(f"  耗时: {step_time:.1f}秒")
            
            # 打印详细的错误堆栈
            import traceback
            error_traceback = traceback.format_exc()
            print(f"  错误详情:\n{error_traceback}")
            
            logger.error(f"步骤 {step_num} ({step_name}) 执行失败: {e}")
            logger.error(f"  耗时: {step_time:.1f}秒")
            logger.error(f"  错误详情:\n{error_traceback}")
            failed_steps.append((step_num, step_name, str(e)))
            
            # 继续执行下一步骤（不中断）
            print(f"  继续执行下一步骤...")
            logger.info(f"  继续执行下一步骤...")
    
    total_time = time.time() - total_start_time
    
    print("\n" + "=" * 60)
    print("  流水线执行完成")
    print("=" * 60)
    print(f"总耗时: {total_time:.1f}秒 ({total_time/60:.1f}分钟 / {total_time/3600:.2f}小时)")
    print(f"结束时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    logger.info("=" * 60)
    logger.info("流水线执行完成")
    logger.info(f"总耗时: {total_time:.1f}秒 ({total_time/60:.1f}分钟)")
    logger.info("=" * 60)
    
    # 显示失败步骤汇总
    if failed_steps:
        print(f"\n⚠ 警告: {len(failed_steps)} 个步骤执行失败:")
        logger.warning(f"{len(failed_steps)} 个步骤执行失败:")
        for step_num, step_name, error in failed_steps:
            print(f"  - 步骤 {step_num} ({step_name}): {error}")
            logger.warning(f"  - 步骤 {step_num} ({step_name}): {error}")
        print("\n请检查日志文件: Output/logs/run_pipeline.log")
        return False
    else:
        print("\n✓ 所有步骤执行成功!")
        logger.info("所有步骤执行成功!")
        
        # 运行数据集分析
        print("\n正在分析生成的数据集...")
        logger.info("开始分析数据集...")
        try:
            analyze_dataset()
            logger.info("数据集分析完成")
        except Exception as e:
            print(f"数据集分析失败: {e}")
            logger.error(f"数据集分析失败: {e}")
        
        return True

def print_usage():
    """打印使用说明"""
    print("""
太阳耀斑预测数据集构建流水线（无交互版本）
==========================================

使用方法:
  python run_pipeline.py [start_step] [end_step]

步骤说明:
  1. 提取耀斑标签    - 从NOAA事件文件提取耀斑记录
  2. 裁剪活动区域    - 从HMI磁图裁剪600x600区域
  3. 转换为PNG       - 将FITS转换为PNG图像
  4. 生成FITS数据集  - 从FITS提取29维特征
  5. 生成PNG数据集   - 从PNG提取29维特征
  6. 生成视频        - 生成活动区域演化MP4视频

示例:
  python run_pipeline.py           # 执行所有步骤
  python run_pipeline.py 1 3       # 执行步骤 1 到 3
  python run_pipeline.py 4         # 只执行步骤 4

后台运行（推荐）:
  nohup python run_pipeline.py > pipeline.log 2>&1 &
  
  # 查看实时日志
  tail -f pipeline.log
  
  # 查看进程
  ps aux | grep run_pipeline.py

配置文件: config.py
  - DATA_ROOT: 数据根目录路径
  - START_YEAR, END_YEAR: 年份范围
  - mag_threshold: 磁场归一化阈值 (200/500/1000)
  - prediction_hours: 耀斑预测窗口，int 或 list[int]（Step4/5 一次写入多列）
  - max_workers: 并行进程数

日志文件:
  - Output/logs/run_pipeline.log  # 主流水线日志
  - Output/logs/step1_flare_labels.log
  - Output/logs/step2_crop_regions.log
  - Output/logs/step3_convert_png.log
  - 等等...

注意事项:
  - 此版本不需要任何交互，适合后台运行
  - 如果某个步骤失败，会继续执行后续步骤
  - 所有输出都会记录到日志文件中
  - 建议先运行 'python check_data_structure.py' 检查数据
""")

if __name__ == "__main__":
    args = sys.argv[1:]
    
    if len(args) == 0:
        # 执行所有步骤
        success = run_pipeline_no_interaction()
        sys.exit(0 if success else 1)
    elif len(args) == 1:
        if args[0] in ['-h', '--help']:
            print_usage()
            sys.exit(0)
        else:
            try:
                step = int(args[0])
                success = run_pipeline_no_interaction(step, step)
                sys.exit(0 if success else 1)
            except ValueError:
                print("错误: 步骤号必须是整数")
                print_usage()
                sys.exit(1)
    elif len(args) == 2:
        try:
            start_step = int(args[0])
            end_step = int(args[1])
            success = run_pipeline_no_interaction(start_step, end_step)
            sys.exit(0 if success else 1)
        except ValueError:
            print("错误: 步骤号必须是整数")
            print_usage()
            sys.exit(1)
    else:
        print("错误: 参数过多")
        print_usage()
        sys.exit(1)
