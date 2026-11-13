# -*- coding: utf-8 -*-
"""
修正版全量重算驱动脚本 (JW-FD-fixed)。

执行顺序:
  1. Step2b rot180 已发布 FITS -> JW-FD-fixed/fits_600
  2. Step3 单遍读 rot180 FITS，一次生成全部 10 个阈值的 PNG (flipud)
  3. 对每个阈值依次跑 Step5，生成 PNG 版 CSV（全量重写，不增量追加）
  4. Step4 生成唯一一份 FITS 版 CSV（与阈值无关）
  5. 对全部 11 份 CSV 按 split_v2_ar_membership.json（seed 3970）划分
  6. 校验 FITS / PNG / CSV / split 行数一致性

用法:
  python batch_update_thresholds.py
  python batch_update_thresholds.py --dry-run
  python batch_update_thresholds.py --only step2b
  python batch_update_thresholds.py --only step3
  python batch_update_thresholds.py --only step5 --thresholds 1000 2000
  nohup python batch_update_thresholds.py > batch_update.log 2>&1 &
"""

import argparse
import os
import sys
import time
from datetime import datetime

_tmpdir = os.environ.get('TMPDIR') or '/tmp'
os.environ['TMPDIR'] = os.environ['TEMP'] = os.environ['TMP'] = _tmpdir
os.makedirs(os.environ['TMPDIR'], exist_ok=True)

# 与各 step 模块保持一致：必须早于 numpy/scipy 加载
for _var in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS',
             'OPENBLAS_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ.setdefault(_var, '1')


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

from config import (
    PARAMS,
    OUTPUT_PATH,
    START_YEAR,
    END_YEAR,
    year_in_range,
    get_path,
    get_png_dir,
    get_png_thresholds,
    get_output_suffix,
    get_output_suffix_fits,
)
from utils import (
    setup_logging,
    extract_year_from_filename,
    ensure_directory,
    load_existing_csv_column,
)

SPLIT_SEED = 3970
STAGES = ('step2b', 'step3', 'step5', 'step4', 'split')
EXPECTED_FRAMES = 2003969


def get_png_csv_path(threshold):
    """PNG 版 CSV：{OUTPUT_PATH}/label/png/Th{th}/solar_flare_dataset_png_Lat60_Lon60_Th{th}.csv"""
    prev = PARAMS['mag_threshold']
    PARAMS['mag_threshold'] = threshold
    try:
        suffix = get_output_suffix()
    finally:
        PARAMS['mag_threshold'] = prev
    csv_dir = os.path.join(OUTPUT_PATH, 'label', 'png', f'Th{threshold}')
    ensure_directory(csv_dir)
    return os.path.join(csv_dir, f'solar_flare_dataset_png_{suffix}.csv')


def get_fits_csv_path():
    """FITS 版 CSV：{OUTPUT_PATH}/label/fits/solar_flare_dataset_fits_Lat60_Lon60.csv"""
    csv_dir = os.path.join(OUTPUT_PATH, 'label', 'fits')
    ensure_directory(csv_dir)
    return os.path.join(csv_dir, f'solar_flare_dataset_fits_{get_output_suffix_fits()}.csv')


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


def split_counts(csv_path):
    prefix = os.path.splitext(csv_path)[0]
    train = count_csv_rows(f"{prefix}_train.csv")
    val = count_csv_rows(f"{prefix}_val.csv")
    test = count_csv_rows(f"{prefix}_test.csv")
    return train, val, test


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


def dry_run(thresholds):
    """统计各阈值待补 FITS / PNG / CSV 数量（不读写数据）。"""
    source_folder = get_path('fits_600_source')
    input_folder = get_path('fits_600')
    source_files = collect_fits_files(source_folder)
    rotated_files = collect_fits_files(input_folder)

    rows = []
    for threshold in thresholds:
        output_folder = get_png_dir(threshold)
        missing_png = sum(
            1 for f in rotated_files
            if not os.path.exists(fits_to_png_path(f, input_folder, output_folder))
        )
        csv_path = get_png_csv_path(threshold)
        png_count = count_files(output_folder, '.png')
        existing_csv_names = load_existing_csv_column(csv_path, 'image_filename')
        rows.append({
            'threshold': threshold,
            'png_count': png_count,
            'missing_png': missing_png,
            'csv_rows': count_csv_rows(csv_path),
            'missing_csv': max(0, png_count - len(existing_csv_names)),
        })

    fits_csv = get_fits_csv_path()
    return {
        'source_fits_count': len(source_files),
        'rotated_fits_count': len(rotated_files),
        'missing_rotated': max(0, len(source_files) - len(rotated_files)),
        'per_threshold': rows,
        'fits_csv_rows': count_csv_rows(fits_csv),
        'fits_csv': fits_csv,
    }


def verify_threshold(threshold, expected_fits=None, require_split=True):
    """校验某阈值下 PNG 数 == FITS 帧数 == CSV 行数 == split 三份之和。"""
    fits_count = count_files(get_path('fits_600'), '.fits')
    png_count = count_files(get_png_dir(threshold), '.png')
    csv_path = get_png_csv_path(threshold)
    csv_rows = count_csv_rows(csv_path)
    train, val, test = split_counts(csv_path)
    split_total = train + val + test

    issues = []
    if expected_fits is not None and fits_count != expected_fits:
        issues.append(f"FITS 数量 {fits_count} != 期望 {expected_fits}")
    if png_count != fits_count:
        issues.append(f"PNG {png_count} != FITS {fits_count}")
    if csv_rows != png_count:
        issues.append(f"CSV {csv_rows} != PNG {png_count}")
    if require_split and split_total != csv_rows:
        issues.append(f"split 合计 {split_total} != CSV {csv_rows}")

    return {
        'kind': f'PNG Th{threshold}',
        'fits_count': fits_count,
        'png_count': png_count,
        'csv_rows': csv_rows,
        'split': (train, val, test),
        'split_total': split_total,
        'ok': not issues,
        'issues': issues,
    }


def verify_fits(expected_fits=None, require_split=True):
    """校验 FITS 版 CSV：行数 == FITS 帧数 == split 三份之和。"""
    fits_count = count_files(get_path('fits_600'), '.fits')
    csv_path = get_fits_csv_path()
    csv_rows = count_csv_rows(csv_path)
    train, val, test = split_counts(csv_path)
    split_total = train + val + test

    issues = []
    if expected_fits is not None and fits_count != expected_fits:
        issues.append(f"FITS 数量 {fits_count} != 期望 {expected_fits}")
    if csv_rows != fits_count:
        issues.append(f"FITS CSV {csv_rows} != FITS {fits_count}")
    if require_split and split_total != csv_rows:
        issues.append(f"split 合计 {split_total} != CSV {csv_rows}")

    return {
        'kind': 'FITS',
        'fits_count': fits_count,
        'csv_rows': csv_rows,
        'split': (train, val, test),
        'split_total': split_total,
        'ok': not issues,
        'issues': issues,
    }


def run_step2b(log, skip_existing=True):
    import step2b_rotate_fits as step2b

    log("========== Step2b: rot180 fits_600_raw -> fits_600 ==========")
    t0 = time.time()
    result = step2b.rotate_fits(skip_existing=skip_existing)
    log(f"Step2b 结果: {result}")
    log(f"Step2b 耗时 {time.time() - t0:.1f}s")
    return result


def run_step3(thresholds, log):
    import step3_convert_to_png as step3

    log(f"========== Step3: 单遍生成 {thresholds} 全部阈值 PNG (flipud) ==========")
    t0 = time.time()
    result = step3.convert_to_png(skip_existing=True, thresholds=thresholds)
    log(f"Step3 结果: {result}")
    log(f"Step3 耗时 {time.time() - t0:.1f}s")
    return result


def run_step5(threshold, log, resume_csv=False):
    import step5_generate_dataset_png as step5

    PARAMS['mag_threshold'] = threshold
    csv_path = get_png_csv_path(threshold)

    log(f"========== Step5 Th{threshold} ==========")
    t0 = time.time()
    if resume_csv:
        log(f"Step5: 增量追加已有 CSV -> {csv_path}")
        result = step5.generate_dataset(skip_existing=True, output_csv=csv_path)
    else:
        log(f"Step5: 全量生成 CSV -> {csv_path}")
        result = step5.generate_dataset(skip_existing=False, output_csv=csv_path)
    log(f"Step5 Th{threshold} 结果: {result}")
    log(f"Step5 Th{threshold} 耗时 {time.time() - t0:.1f}s")
    return result


def run_step4(log, resume_csv=False):
    import step4_generate_dataset_fits as step4

    csv_path = get_fits_csv_path()

    log("========== Step4: FITS 版 CSV（与阈值无关，只生成一份）==========")
    t0 = time.time()
    result = step4.generate_dataset(skip_existing=resume_csv, output_csv=csv_path)
    log(f"Step4 结果: {result}")
    log(f"Step4 耗时 {time.time() - t0:.1f}s")
    return result


def run_split(thresholds, log):
    from split_dataset import split_csv

    log_dir = get_path('log_folder')
    ensure_directory(log_dir)
    results = {}

    for threshold in thresholds:
        csv_path = get_png_csv_path(threshold)
        if not os.path.exists(csv_path):
            log(f"Split: 跳过 Th{threshold}（CSV 不存在）")
            continue
        log_path = os.path.join(log_dir, f'dataset_split_log_PNG_{SPLIT_SEED}_Th{threshold}.txt')
        results[f'Th{threshold}'] = split_csv(csv_path, seed=SPLIT_SEED, log_path=log_path)
        log(f"Split Th{threshold}: {results[f'Th{threshold}']}")

    fits_csv = get_fits_csv_path()
    if os.path.exists(fits_csv):
        log_path = os.path.join(log_dir, f'dataset_split_log_FITS_{SPLIT_SEED}.txt')
        results['fits'] = split_csv(fits_csv, seed=SPLIT_SEED, log_path=log_path)
        log(f"Split FITS: {results['fits']}")
    else:
        log("Split: 跳过 FITS（CSV 不存在）")

    return results


def main():
    parser = argparse.ArgumentParser(description="JW-FD-fixed 全量重算驱动")
    parser.add_argument(
        '--thresholds',
        nargs='+',
        type=int,
        default=None,
        help=f"磁场阈值列表，默认 {PARAMS['png_thresholds']}",
    )
    parser.add_argument(
        '--only',
        choices=STAGES,
        default=None,
        help='只跑某一阶段（step2b / step3 / step5 / step4 / split）',
    )
    parser.add_argument('--dry-run', action='store_true', help='仅统计待补数量，不执行')
    parser.add_argument('--skip-split', action='store_true', help='跳过 train/val/test 划分')
    parser.add_argument('--fail-fast', action='store_true', help='某阶段失败时立即退出')
    parser.add_argument(
        '--resume-csv',
        action='store_true',
        help='Step4/5 增量追加已有 CSV（默认全量重写；勿在 split 前混用）',
    )
    parser.add_argument(
        '--no-skip-existing-fits',
        action='store_true',
        help='Step2b 不跳过已存在的 rot180 FITS',
    )
    args = parser.parse_args()

    thresholds = sorted({int(t) for t in (args.thresholds or get_png_thresholds())})

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    logger = setup_logging(f'batch_update_{timestamp}')
    log = logger.info

    print("=" * 60)
    print("  JW-FD-fixed 全量重算")
    print("=" * 60)
    print(f"阈值列表: {thresholds} ({len(thresholds)} 套 PNG + 1 套 FITS CSV = {len(thresholds) + 1} 份)")
    print(f"阶段: {args.only or ' -> '.join(STAGES)}")
    print(f"期望帧数: {EXPECTED_FRAMES}")
    print(f"日志目录: {get_path('log_folder')}")
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    if args.dry_run:
        info = dry_run(thresholds)
        print("\n【Dry-run 统计】")
        print(f"已发布 FITS 帧数: {info['source_fits_count']}")
        print(f"rot180 FITS 帧数: {info['rotated_fits_count']} (待补 {info['missing_rotated']})")
        for row in info['per_threshold']:
            print(
                f"Th{row['threshold']}: PNG={row['png_count']}, 待补PNG={row['missing_png']}, "
                f"CSV行={row['csv_rows']}, 待补CSV≈{row['missing_csv']}"
            )
        print(f"FITS CSV 行数: {info['fits_csv_rows']} ({info['fits_csv']})")
        return 0

    try:
        import scipy.linalg  # noqa: F401
    except ImportError as e:
        print(f"依赖检查失败（scipy/MKL）: {e}")
        return 1

    stages = [args.only] if args.only else list(STAGES)
    if args.skip_split and 'split' in stages:
        stages.remove('split')

    failed = []
    t_start = time.time()

    for stage in stages:
        try:
            if stage == 'step2b':
                run_step2b(log, skip_existing=not args.no_skip_existing_fits)
            elif stage == 'step3':
                run_step3(thresholds, log)
            elif stage == 'step5':
                for threshold in thresholds:
                    try:
                        run_step5(threshold, log, resume_csv=args.resume_csv)
                    except Exception as e:
                        msg = f"Step5 Th{threshold} 失败: {e}"
                        print(msg)
                        logger.error(msg)
                        failed.append((f'step5:Th{threshold}', str(e)))
                        if args.fail_fast:
                            raise
            elif stage == 'step4':
                run_step4(log, resume_csv=args.resume_csv)
            elif stage == 'split':
                run_split(thresholds, log)
        except Exception as e:
            msg = f"阶段 {stage} 失败: {e}"
            print(msg)
            logger.error(msg)
            failed.append((stage, str(e)))
            if args.fail_fast:
                break

    # ---- 校验 ----
    require_split = 'split' in stages or args.only is None
    require_split = require_split and not args.skip_split
    print("\n【校验】")
    verifications = []
    expected_fits = EXPECTED_FRAMES if args.only is None else None
    for threshold in thresholds:
        v = verify_threshold(threshold, expected_fits=expected_fits, require_split=require_split)
        if expected_fits is None:
            expected_fits = v['fits_count'] if v['fits_count'] else expected_fits
        verifications.append(v)
    verifications.append(verify_fits(expected_fits=expected_fits, require_split=require_split))

    for v in verifications:
        status = 'OK' if v['ok'] else 'FAIL'
        print(f"  [{status}] {v['kind']}: {v}")
        log(f"校验 {v['kind']}: ok={v['ok']}, {v}")
        if not v['ok']:
            failed.append((v['kind'], '; '.join(v['issues'])))

    print("\n" + "=" * 60)
    print(f"总耗时 {time.time() - t_start:.1f}s")
    if failed:
        print(f"失败 {len(failed)} 项:")
        for name, err in failed:
            print(f"  {name}: {err}")
        return 1
    print("全部阶段处理成功")
    print("=" * 60)
    return 0


if __name__ == '__main__':
    sys.exit(main())
