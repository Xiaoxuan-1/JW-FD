# -*- coding: utf-8 -*-
"""
批量增量补 PNG + CSV：对多个 mag_threshold 依次执行 Step3/Step5/Split。

用法:
  python batch_update_thresholds.py
  python batch_update_thresholds.py --thresholds 1000
  python batch_update_thresholds.py --dry-run
  nohup python batch_update_thresholds.py > batch_update.log 2>&1 &
"""

import argparse
import os
import sys
import time
from datetime import datetime

os.environ['TMPDIR'] = '/data/shaomf/tmp'
os.environ['TEMP'] = '/data/shaomf/tmp'
os.environ['TMP'] = '/data/shaomf/tmp'
os.makedirs(os.environ['TMPDIR'], exist_ok=True)


def ensure_mkl_runtime():
    """确保 scipy 可加载 libmkl_rt.so.1（conda 仅提供 .so.2 时的兼容处理）。"""
    if os.environ.get('_JWFD_MKL_READY') == '1':
        return

    conda_lib = os.path.realpath(os.path.join(os.path.dirname(sys.executable), '..', 'lib'))
    so1 = os.path.join(conda_lib, 'libmkl_rt.so.1')
    so2 = os.path.join(conda_lib, 'libmkl_rt.so.2')

    if os.path.exists(so1) or not os.path.exists(so2):
        os.environ['_JWFD_MKL_READY'] = '1'
        return

    try:
        os.symlink('libmkl_rt.so.2', so1)
        os.environ['_JWFD_MKL_READY'] = '1'
        return
    except OSError:
        pass

    mkl_dir = os.path.join(os.environ['TMPDIR'], 'mkl_lib')
    os.makedirs(mkl_dir, exist_ok=True)
    tmp_so1 = os.path.join(mkl_dir, 'libmkl_rt.so.1')
    if not os.path.exists(tmp_so1):
        os.symlink(so2, tmp_so1)

    ld_paths = [mkl_dir, conda_lib]
    if os.environ.get('LD_LIBRARY_PATH'):
        ld_paths.append(os.environ['LD_LIBRARY_PATH'])
    os.environ['LD_LIBRARY_PATH'] = os.pathsep.join(ld_paths)
    os.environ['_JWFD_MKL_READY'] = '1'
    os.execve(sys.executable, [sys.executable] + sys.argv, os.environ)


ensure_mkl_runtime()

from config import PARAMS, OUTPUT_PATH, START_YEAR, END_YEAR, year_in_range, get_path, get_output_suffix
from utils import (
    setup_logging,
    extract_year_from_filename,
    ensure_directory,
    load_existing_csv_column,
)

DEFAULT_THRESHOLDS = [400, 600, 800, 1000, 2000]
SPLIT_SEED = 62


def get_png_csv_path(threshold):
    suffix = get_output_suffix()
    csv_dir = os.path.join(OUTPUT_PATH, 'label', 'png', f'Th{threshold}')
    ensure_directory(csv_dir)
    return os.path.join(csv_dir, f'solar_flare_dataset_png_{suffix}.csv')


def count_files(root, suffix):
    """递归统计指定后缀文件数（按年份过滤）。"""
    count = 0
    if not os.path.isdir(root):
        return 0
    for dirpath, _, files in os.walk(root):
        for name in files:
            if name.endswith(suffix):
                if year_in_range(extract_year_from_filename(name)):
                    count += 1
    return count


def count_csv_rows(csv_path):
    if not os.path.exists(csv_path):
        return 0
    with open(csv_path, 'r', encoding='utf-8') as f:
        lines = sum(1 for _ in f)
    return max(0, lines - 1)


def fits_to_png_path(fits_file, input_folder, output_folder):
    subdir = os.path.dirname(fits_file)
    relative_path = os.path.relpath(subdir, input_folder)
    output_dir = os.path.join(output_folder, relative_path)
    return os.path.join(output_dir, os.path.basename(fits_file).replace('.fits', '.png'))


def collect_fits_files(input_folder):
    fits_files = []
    for dirpath, _, files in os.walk(input_folder):
        for name in files:
            if name.endswith('.fits'):
                path = os.path.join(dirpath, name)
                if year_in_range(extract_year_from_filename(path)):
                    fits_files.append(path)
    fits_files.sort()
    return fits_files


def dry_run_threshold(threshold):
    """统计某阈值待补 PNG 数量（不读写数据）。"""
    PARAMS['mag_threshold'] = threshold
    input_folder = get_path('fits_600')
    output_folder = get_path('png_600')
    csv_path = get_png_csv_path(threshold)

    fits_files = collect_fits_files(input_folder)
    missing_png = 0
    for fits_file in fits_files:
        png_path = fits_to_png_path(fits_file, input_folder, output_folder)
        if not os.path.exists(png_path):
            missing_png += 1

    png_count = count_files(output_folder, '.png')
    csv_rows = count_csv_rows(csv_path)
    existing_csv_names = load_existing_csv_column(csv_path, 'image_filename')
    missing_csv = max(0, png_count - len(existing_csv_names))

    return {
        'threshold': threshold,
        'fits_count': len(fits_files),
        'png_count': png_count,
        'missing_png': missing_png,
        'csv_rows': csv_rows,
        'missing_csv': missing_csv,
        'csv_path': csv_path,
    }


def verify_threshold(threshold, expected_fits=None):
    """校验 FITS / PNG / CSV / split 行数一致性。"""
    PARAMS['mag_threshold'] = threshold
    fits_count = count_files(get_path('fits_600'), '.fits')
    png_count = count_files(get_path('png_600'), '.png')
    csv_path = get_png_csv_path(threshold)
    csv_rows = count_csv_rows(csv_path)

    prefix = os.path.splitext(csv_path)[0]
    train_rows = count_csv_rows(f"{prefix}_train.csv")
    val_rows = count_csv_rows(f"{prefix}_val.csv")
    test_rows = count_csv_rows(f"{prefix}_test.csv")
    split_total = train_rows + val_rows + test_rows

    issues = []
    if expected_fits is not None and fits_count != expected_fits:
        issues.append(f"FITS 数量 {fits_count} != 期望 {expected_fits}")
    if png_count != fits_count:
        issues.append(f"PNG {png_count} != FITS {fits_count}")
    if csv_rows != png_count:
        issues.append(f"CSV {csv_rows} != PNG {png_count}")
    if split_total != csv_rows:
        issues.append(f"split 合计 {split_total} != CSV {csv_rows}")

    return {
        'threshold': threshold,
        'fits_count': fits_count,
        'png_count': png_count,
        'csv_rows': csv_rows,
        'split_total': split_total,
        'ok': len(issues) == 0,
        'issues': issues,
    }


def process_threshold(threshold, skip_step3=False, skip_split=False, logger=None):
    """对单个阈值执行 Step3 -> Step5 -> Split -> 校验。"""
    import step3_convert_to_png as step3
    import step5_generate_dataset_png as step5
    from split_dataset import split_csv

    PARAMS['mag_threshold'] = threshold
    log = logger.info if logger else print

    log(f"========== Th{threshold} 开始 ==========")
    t0 = time.time()

    if skip_step3:
        log("Step3: 跳过（PNG 已就绪）")
    else:
        step3_result = step3.convert_to_png(skip_existing=True)
        log(f"Step3: {step3_result}")

    csv_path = get_png_csv_path(threshold)
    has_existing_csv = os.path.exists(csv_path) and os.path.getsize(csv_path) > 0
    if has_existing_csv:
        log(f"Step5: 增量追加已有 CSV -> {csv_path}")
        step5_result = step5.generate_dataset(skip_existing=True, output_csv=csv_path)
    else:
        log(f"Step5: 全量生成 CSV -> {csv_path}")
        step5_result = step5.generate_dataset(skip_existing=False, output_csv=csv_path)
    log(f"Step5: {step5_result}")

    if not skip_split:
        log_path = os.path.join(
            OUTPUT_PATH,
            f'dataset_split_log_PNG_{SPLIT_SEED}_Th{threshold}.txt',
        )
        split_result = split_csv(csv_path, seed=SPLIT_SEED, log_path=log_path)
        log(f"Split: {split_result}")

    verify = verify_threshold(threshold)
    elapsed = time.time() - t0
    log(f"校验 Th{threshold}: ok={verify['ok']}, {verify}")
    log(f"========== Th{threshold} 完成，耗时 {elapsed:.1f}s ==========")

    if not verify['ok']:
        raise RuntimeError(f"Th{threshold} 校验失败: {verify['issues']}")

    return verify


def main():
    parser = argparse.ArgumentParser(description="批量增量补 PNG + CSV")
    parser.add_argument(
        '--thresholds',
        nargs='+',
        type=int,
        default=DEFAULT_THRESHOLDS,
        help=f'磁场阈值列表，默认 {DEFAULT_THRESHOLDS}',
    )
    parser.add_argument('--dry-run', action='store_true', help='仅统计待补数量，不执行')
    parser.add_argument('--skip-step3', action='store_true', help='跳过 Step3（PNG 已生成时使用）')
    parser.add_argument('--skip-split', action='store_true', help='跳过 train/val/test 划分')
    parser.add_argument('--fail-fast', action='store_true', help='某阈值失败时立即退出')
    args = parser.parse_args()

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    logger = setup_logging(f'batch_update_{timestamp}')

    print("=" * 60)
    print("  批量增量补 PNG + CSV")
    print("=" * 60)
    print(f"阈值列表: {args.thresholds}")
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    if not args.dry_run:
        try:
            import scipy.linalg  # noqa: F401
        except ImportError as e:
            print(f"依赖检查失败（scipy/MKL）: {e}")
            return 1

    if args.dry_run:
        print("\n【Dry-run 统计】")
        expected_fits = None
        for th in args.thresholds:
            info = dry_run_threshold(th)
            if expected_fits is None:
                expected_fits = info['fits_count']
            print(
                f"Th{th}: FITS={info['fits_count']}, PNG={info['png_count']}, "
                f"待补PNG={info['missing_png']}, CSV行={info['csv_rows']}, "
                f"待补CSV≈{info['missing_csv']}"
            )
        print(f"\n参考 FITS 总数: {expected_fits}")
        return 0

    failed = []
    for th in args.thresholds:
        try:
            process_threshold(
                th,
                skip_step3=args.skip_step3,
                skip_split=args.skip_split,
                logger=logger,
            )
        except Exception as e:
            msg = f"Th{th} 失败: {e}"
            print(msg)
            logger.error(msg)
            failed.append((th, str(e)))
            if args.fail_fast:
                break

    print("\n" + "=" * 60)
    if failed:
        print(f"完成，{len(failed)} 个阈值失败: {[t for t, _ in failed]}")
        return 1
    print("全部阈值处理成功")
    print("=" * 60)
    return 0


if __name__ == '__main__':
    sys.exit(main())
