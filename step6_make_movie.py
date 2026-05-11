# -*- coding: utf-8 -*-
"""
步骤6: 生成活动区域演化视频
输入: PNG图像序列
输出: MP4视频文件
"""

import os
import gc
import imageio.v2 as imageio
from tqdm import tqdm
from multiprocessing import Pool
from config import PARAMS, START_YEAR, END_YEAR, year_in_range, get_path
from utils import setup_logging, extract_year_from_filename

def make_movie_worker(args):
    """
    Worker函数：为单个活动区域生成MP4视频

    Args:
        args: (ar_name, ar_path, png_files, output_path, fps) 元组
            png_files: 已按时间排序的 PNG 文件名列表（basename）

    Returns:
        (ar_name, success, png_count, duration, output_path) 元组
    """
    ar_name, ar_path, png_files, output_path, fps = args
    import numpy as np

    try:
        if len(png_files) == 0:
            return ar_name, False, 0, 0, output_path
        
        # 确保输出是.mp4
        if not output_path.endswith('.mp4'):
            output_path = output_path.replace('.gif', '.mp4')
        
        # 读取第一张图像确定尺寸
        first_img = imageio.imread(os.path.join(ar_path, png_files[0]))
        original_shape = first_img.shape
        
        # 调整为16的倍数以避免FFMPEG警告 (600->608)
        h, w = original_shape[:2]
        target_h = ((h + 15) // 16) * 16
        target_w = ((w + 15) // 16) * 16
        
        # 使用imageio-ffmpeg写入MP4
        try:
            writer = imageio.get_writer(output_path, format='FFMPEG', mode='I', 
                                         fps=fps, codec='libx264', 
                                         pixelformat='yuv420p')
        except Exception:
            writer = imageio.get_writer(output_path, format='FFMPEG', mode='I', fps=fps)
        
        for png_file in png_files:
            img_path = os.path.join(ar_path, png_file)
            img = imageio.imread(img_path)
            
            # 灰度图转RGB
            if len(img.shape) == 2:
                img = np.stack([img, img, img], axis=-1)
            
            # 调整到目标尺寸
            if img.shape[:2] != (target_h, target_w):
                from PIL import Image
                pil_img = Image.fromarray(img)
                pil_img = pil_img.resize((target_w, target_h), Image.Resampling.LANCZOS)
                img = np.array(pil_img)
            
            writer.append_data(img)
        
        writer.close()
        gc.collect()
        
        duration = len(png_files) / fps
        return ar_name, True, len(png_files), duration, output_path
        
    except Exception as e:
        return ar_name, False, 0, 0, output_path


def make_movie(ar_folder, output_path, fps=60):
    """
    为单个活动区域生成MP4视频（保留用于单独调用）

    Args:
        ar_folder: 活动区域图像文件夹路径
        output_path: 输出视频路径
        fps: 帧率，默认60帧/秒
    """
    ar_name = os.path.basename(ar_folder)
    if not os.path.isdir(ar_folder):
        return False
    all_png = sorted([f for f in os.listdir(ar_folder) if f.endswith('.png')])
    filtered = [f for f in all_png if year_in_range(extract_year_from_filename(f))]
    if not filtered:
        print(f"年份范围 [{START_YEAR}, {END_YEAR}] 内无 PNG 帧，跳过 AR{ar_name}")
        return False
    _, success, _, _, _ = make_movie_worker((ar_name, ar_folder, filtered, output_path, fps))
    return success

def make_all_movies(fps=60):
    """
    为所有活动区域生成视频（多进程优化版）
    
    Args:
        fps: 帧率，默认60帧/秒
    """
    logger = setup_logging('step6_make_movie')
    logger.info("开始生成活动区域演化视频...")
    
    png_folder = get_path('png_600')
    output_folder = get_path('movies')
    
    # 确保输出目录存在
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)
    
    # 获取所有活动区域文件夹
    ar_folders = sorted([f for f in os.listdir(png_folder) 
                        if os.path.isdir(os.path.join(png_folder, f))])
    
    if len(ar_folders) == 0:
        print("没有找到活动区域文件夹")
        logger.warning("没有找到活动区域文件夹")
        return
    
    print(f"找到 {len(ar_folders)} 个活动区域目录")
    print(f"输出目录: {output_folder}")
    print(f"帧率: {fps} fps")
    print("-" * 50)

    logger.info(f"找到 {len(ar_folders)} 个活动区域目录")
    logger.info(f"输出目录: {output_folder}")
    logger.info(f"帧率: {fps} fps")

    # 准备任务列表（每个 AR 只包含年份范围内的 PNG）
    tasks = []
    for ar_name in ar_folders:
        ar_path = os.path.join(png_folder, ar_name)
        all_png = sorted([f for f in os.listdir(ar_path) if f.endswith('.png')])
        filtered = [f for f in all_png if year_in_range(extract_year_from_filename(f))]
        if not filtered:
            continue
        output_path = os.path.join(output_folder, f"AR{ar_name}_evolution.mp4")
        tasks.append((ar_name, ar_path, filtered, output_path, fps))

    ar_msg = f"年份过滤 [{START_YEAR}, {END_YEAR}]：处理 {len(tasks)}/{len(ar_folders)} 个 AR（目录内有范围内帧）"
    print(ar_msg)
    logger.info(ar_msg)

    if len(tasks) == 0:
        print("没有活动区域在年份范围内包含 PNG，退出")
        logger.warning("没有活动区域在年份范围内包含 PNG")
        return
    
    # 多进程或单进程处理
    if PARAMS['use_multiprocess'] and len(tasks) > 1:
        max_workers = min(PARAMS['max_workers'], len(tasks))
        print(f"使用 {max_workers} 个进程并行生成...")
        
        with Pool(max_workers) as pool:
            results = list(tqdm(
                pool.imap_unordered(make_movie_worker, tasks),
                total=len(tasks),
                desc="生成视频"
            ))
    else:
        # 单进程版本
        results = []
        for task in tqdm(tasks, desc="生成视频"):
            results.append(make_movie_worker(task))
    
    # 统计结果
    success_count = 0
    for ar_name, success, png_count, duration, output_path in results:
        if success:
            print(f"  AR{ar_name}: {png_count}帧, 时长{duration:.1f}秒 -> {output_path}")
            logger.info(f"AR{ar_name}: {png_count}帧, 时长{duration:.1f}秒")
            success_count += 1
        else:
            print(f"  AR{ar_name}: 生成失败")
            logger.warning(f"AR{ar_name}: 生成失败")
    
    print("-" * 50)
    print(f"步骤6完成: 成功生成 {success_count}/{len(tasks)} 个视频")
    print(f"视频保存在: {output_folder}")

    logger.info(f"成功生成 {success_count}/{len(tasks)} 个视频")
    logger.info(f"视频保存在: {output_folder}")

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='生成活动区域演化视频')
    parser.add_argument('--fps', type=int, default=60, help='帧率 (默认: 60)')
    parser.add_argument('--ar', type=str, default=None, help='指定活动区域编号 (如: 3534)')
    
    args = parser.parse_args()
    
    if args.ar:
        # 生成单个活动区域的视频
        png_folder = get_path('png_600')
        ar_path = os.path.join(png_folder, args.ar)
        
        if not os.path.exists(ar_path):
            print(f"错误: 活动区域 {args.ar} 不存在")
        else:
            output_folder = get_path('movies')
            if not os.path.exists(output_folder):
                os.makedirs(output_folder)
            output_path = os.path.join(output_folder, f"AR{args.ar}_evolution.mp4")
            
            print(f"生成活动区域 AR{args.ar} 的演化视频...")
            if make_movie(ar_path, output_path, args.fps):
                print(f"视频已保存: {output_path}")
    else:
        # 生成所有活动区域的视频
        make_all_movies(fps=args.fps)
