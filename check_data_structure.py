# -*- coding: utf-8 -*-
"""
数据结构检测工具
用于验证多年份数据的完整性和结构
"""

import os
import glob
from config import DATA_ROOT, START_YEAR, END_YEAR, get_srs_folders, get_events_folders, get_fits_folders

def check_data_structure():
    """检测数据结构完整性"""
    print("=" * 70)
    print("  多年份数据结构检测")
    print("=" * 70)
    print(f"数据根目录: {DATA_ROOT}")
    print(f"年份范围: {START_YEAR} - {END_YEAR}")
    print()
    
    # 检查根目录
    if not os.path.exists(DATA_ROOT):
        print(f"❌ 错误: 数据根目录不存在: {DATA_ROOT}")
        print("   请修改 config.py 中的 DATA_ROOT 路径")
        return False
    
    print("✓ 数据根目录存在")
    print()
    
    # 检查SRS数据
    print("-" * 70)
    print("检查SRS报告:")
    print("-" * 70)
    srs_folders = get_srs_folders()
    
    if not srs_folders:
        print("❌ 未找到任何SRS文件夹")
        return False
    
    print(f"找到 {len(srs_folders)} 个年份的SRS数据:")
    total_srs_files = 0
    
    for year, folder in sorted(srs_folders):
        srs_files = glob.glob(os.path.join(folder, "*.txt"))
        total_srs_files += len(srs_files)
        print(f"  {year}: {folder}")
        print(f"        文件数: {len(srs_files)}")
    
    print(f"\n总计: {total_srs_files} 个SRS文件")
    print()
    
    # 检查Events数据
    print("-" * 70)
    print("检查Events文件:")
    print("-" * 70)
    events_folders = get_events_folders()
    
    if not events_folders:
        print("❌ 未找到任何Events文件夹")
        return False
    
    print(f"找到 {len(events_folders)} 个年份的Events数据:")
    total_events_files = 0
    
    for year, folder in sorted(events_folders):
        events_files = glob.glob(os.path.join(folder, "*.txt"))
        total_events_files += len(events_files)
        print(f"  {year}: {folder}")
        print(f"        文件数: {len(events_files)}")
    
    print(f"\n总计: {total_events_files} 个Events文件")
    print()
    
    # 检查FITS数据
    print("-" * 70)
    print("检查FITS文件:")
    print("-" * 70)
    fits_folders = get_fits_folders()
    
    if not fits_folders:
        print("❌ 未找到任何FITS文件夹")
        return False
    
    print(f"找到 {len(fits_folders)} 个年份+月份的FITS数据:")
    
    # 按年份分组统计
    year_stats = {}
    total_fits_files = 0
    
    for year, month, folder in sorted(fits_folders):
        fits_files = glob.glob(os.path.join(folder, "*.fits"))
        file_count = len(fits_files)
        total_fits_files += file_count
        
        if year not in year_stats:
            year_stats[year] = {'months': [], 'total_files': 0}
        
        year_stats[year]['months'].append(month)
        year_stats[year]['total_files'] += file_count
    
    for year in sorted(year_stats.keys()):
        stats = year_stats[year]
        months_str = ', '.join([f"{m:02d}" for m in sorted(stats['months'])])
        print(f"  {year}: {len(stats['months'])} 个月 (月份: {months_str})")
        print(f"        文件数: {stats['total_files']}")
    
    print(f"\n总计: {total_fits_files} 个FITS文件")
    print()
    
    # 数据完整性检查
    print("-" * 70)
    print("数据完整性检查:")
    print("-" * 70)
    
    srs_years = set(year for year, _ in srs_folders)
    events_years = set(year for year, _ in events_folders)
    fits_years = set(year for year, _, _ in fits_folders)
    
    all_years = srs_years | events_years | fits_years
    
    for year in sorted(all_years):
        has_srs = year in srs_years
        has_events = year in events_years
        has_fits = year in fits_years
        
        status = []
        if has_srs:
            status.append("✓ SRS")
        else:
            status.append("✗ SRS")
        
        if has_events:
            status.append("✓ Events")
        else:
            status.append("✗ Events")
        
        if has_fits:
            status.append("✓ FITS")
        else:
            status.append("✗ FITS")
        
        status_str = " | ".join(status)
        
        if has_srs and has_events and has_fits:
            print(f"  {year}: {status_str} ✓ 完整")
        else:
            print(f"  {year}: {status_str} ⚠ 不完整")
    
    print()
    
    # 总结
    print("=" * 70)
    print("检测总结:")
    print("=" * 70)
    print(f"✓ SRS数据: {len(srs_folders)} 个年份, {total_srs_files} 个文件")
    print(f"✓ Events数据: {len(events_folders)} 个年份, {total_events_files} 个文件")
    print(f"✓ FITS数据: {len(year_stats)} 个年份, {total_fits_files} 个文件")
    print()
    
    if len(srs_folders) > 0 and len(events_folders) > 0 and len(fits_folders) > 0:
        print("✓ 数据结构检测通过，可以开始运行流水线")
        return True
    else:
        print("❌ 数据结构不完整，请检查数据路径配置")
        return False

if __name__ == "__main__":
    check_data_structure()
