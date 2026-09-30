#!/usr/bin/env python3
"""JW-FD split-v2 seed search (rejection sampling). Does not rewrite labels.

Pre-registered rules (frozen before any Mag_TH retraining):
  * Split unit = AR. C1/M1/M5/X1 share one assignment.
  * No NOAA ids, textbook morphology, or isolated-X frame templates in the rule.
  * Strata: X_multi (n_X>=2) / X_single / M5-X / M1-M5 / C-only / Quiet.
    n_X = onsets of flare_label_X1.0_1hr (0 onset + X 24h >0 counts as single).
  * Nested n_frames tertiles inside a stratum when each tertile has >= MIN_TERTILE_N ARs.
  * 80/10/10 inside each cell; AR ids sorted then shuffled (CSV-order independent).
  * Reject a seed unless ALL gates pass. First seed in SEED_START, START+1, ... wins.

Gates:
  * val and test each have >= MIN_POS_ARS X-positive ARs and M5-positive ARs
  * no AR holds > ALPHA of 24h positive frames in val or test (C1/M1/M5/X1)
  * val/test 24h positive-frame ratio in [RATIO_LO, RATIO_HI] for C1/M1/M5/X1
  * |Cohen d| of AR-median unsigned flux and NL length (all ARs, val vs test) < D_MAX

Feature gaps on the small X-AR subset are reported, not used as reject gates
(n~5 is too noisy). Time-based split is not used.

The frozen official assignment is seed=3970, shipped as split_v2_ar_membership.json.
This script only re-searches; it does not emit the train/val/test CSVs.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import random
from collections import defaultdict
from pathlib import Path

_HERE = Path(__file__).resolve().parent
DEFAULT_SRC = Path(
    "/data/Datasets/JW-FD-fixed/label/png/Th1000/"
    "solar_flare_dataset_png_Lat60_Lon60_Th1000.csv"
)
DEFAULT_OFFICIAL = Path("/data/Datasets/JW-FD-fixed/label/png/Th1000")
STEM = "solar_flare_dataset_png_Lat60_Lon60_Th1000"

TRAIN_R = 0.8
VAL_R = 0.1
# Tertile only when each bin can still put ~2 ARs in val and test (n>=20 per bin).
# X_single (35) / X_multi (9) / M5-X (54) stay one cell; Quiet/C/M1-M5 are tertiled.
MIN_TERTILE_N = 20
MIN_POS_ARS = {"X": 5, "M5": 5}
ALPHA = 0.25
RATIO_LO = 0.5
RATIO_HI = 2.0
D_MAX = 0.30
SEED_START = 62
MAX_TRIES = 2000
STRATUM_ORDER = ("X_multi", "X_single", "M5-X", "M1-M5", "C-only", "Quiet")
TASKS = (
    ("C1", "c24"),
    ("M1", "m1"),
    ("M5", "m5"),
    ("X1", "x24"),
)


def _is_pos(v: str) -> int:
    return 1 if v in ("1", "1.0", "True", "true") else 0


def _ar_of(image_path: str) -> str:
    p = (image_path or "").strip().lstrip("./")
    return p.split("/")[0] if p else ""


def n_onsets(seq):
    n = 0
    prev = 0
    for v in seq:
        if v == 1 and prev == 0:
            n += 1
        prev = v
    return n


def median(xs):
    if not xs:
        return 0.0
    ys = sorted(xs)
    m = len(ys) // 2
    if len(ys) % 2:
        return float(ys[m])
    return 0.5 * (ys[m - 1] + ys[m])


def mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def var_s(xs):
    if len(xs) < 2:
        return 0.0
    m = mean(xs)
    return sum((x - m) ** 2 for x in xs) / (len(xs) - 1)


def cohens_d(a, b):
    if len(a) < 2 or len(b) < 2:
        return 0.0
    sp = math.sqrt(0.5 * (var_s(a) + var_s(b)))
    if sp < 1e-12:
        return 0.0
    return (mean(a) - mean(b)) / sp


def build_ar_stats(src: Path) -> dict:
    ars = defaultdict(
        lambda: {
            "n": 0,
            "c24": 0,
            "m1": 0,
            "m5": 0,
            "x24": 0,
            "x1": [],
            "flux": [],
            "nl": [],
        }
    )
    with src.open(newline="", encoding="utf-8", errors="ignore") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ar = _ar_of(row.get("image_path", ""))
            if not ar:
                continue
            a = ars[ar]
            a["n"] += 1
            a["c24"] += _is_pos(row.get("flare_label_C1.0_24hr", "0"))
            a["m1"] += _is_pos(row.get("flare_label_M1.0_24hr", "0"))
            a["m5"] += _is_pos(row.get("flare_label_M5.0_24hr", "0"))
            a["x24"] += _is_pos(row.get("flare_label_X1.0_24hr", "0"))
            a["x1"].append(_is_pos(row.get("flare_label_X1.0_1hr", "0")))
            try:
                a["flux"].append(float(row.get("Total unsigned flux") or 0.0))
            except ValueError:
                a["flux"].append(0.0)
            try:
                a["nl"].append(float(row.get("NL length") or 0.0))
            except ValueError:
                a["nl"].append(0.0)

    out = {}
    for ar, a in ars.items():
        nx = n_onsets(a["x1"])
        if a["x24"] > 0:
            stratum = "X_multi" if nx >= 2 else "X_single"
        elif a["m5"] > 0:
            stratum = "M5-X"
        elif a["m1"] > 0:
            stratum = "M1-M5"
        elif a["c24"] > 0:
            stratum = "C-only"
        else:
            stratum = "Quiet"
        out[ar] = {
            "n": a["n"],
            "c24": a["c24"],
            "m1": a["m1"],
            "m5": a["m5"],
            "x24": a["x24"],
            "n_x": nx,
            "stratum": stratum,
            "flux_med": median(a["flux"]),
            "nl_med": median(a["nl"]),
        }
    return out


def load_official_assignment(official_dir: Path) -> dict:
    assign = {}
    for split in ("train", "val", "test"):
        path = official_dir / "{}_{}.csv".format(STEM, split)
        if not path.exists():
            continue
        with path.open(newline="", encoding="utf-8", errors="ignore") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ar = _ar_of(row.get("image_path", ""))
                if ar and ar not in assign:
                    assign[ar] = split
    return assign


def split_counts(n: int):
    """Integer 80/10/10. Val and test get the same hold-out size (round 10%).

    Avoid float (n*0.1) so 35 does not become val=4 test=3. (n+5)//10 == round(n/10).
    """
    if n <= 0:
        return 0, 0, 0
    if n == 1:
        return 1, 0, 0
    if n == 2:
        return 1, 1, 0
    hold = max(1, (n + 5) // 10)
    if 2 * hold >= n:
        hold = 1
    n_train = n - 2 * hold
    return n_train, hold, hold


def tertile_cells(ar_ids, stats):
    """Return list of AR-id lists. One cell, or three n_frames tertiles."""
    ids = list(ar_ids)
    n = len(ids)
    if n < 3 * MIN_TERTILE_N:
        return [ids]
    ids.sort(key=lambda a: (stats[a]["n"], a))
    cuts = [int(round(n * k / 3.0)) for k in range(4)]
    cells = [ids[cuts[i] : cuts[i + 1]] for i in range(3)]
    if any(len(c) < MIN_TERTILE_N for c in cells):
        return [list(ar_ids)]
    return cells


def assign_for_seed(seed: int, stats: dict) -> dict:
    by_s = defaultdict(list)
    for ar, a in stats.items():
        by_s[a["stratum"]].append(ar)
    rng = random.Random(seed)
    assign = {}
    for stratum in STRATUM_ORDER:
        ar_ids = by_s.get(stratum, [])
        for cell in tertile_cells(ar_ids, stats):
            cell = list(cell)
            cell.sort()
            rng.shuffle(cell)
            n_tr, n_va, _n_te = split_counts(len(cell))
            for i, ar in enumerate(cell):
                if i < n_tr:
                    assign[ar] = "train"
                elif i < n_tr + n_va:
                    assign[ar] = "val"
                else:
                    assign[ar] = "test"
    return assign


def evaluate(assign: dict, stats: dict) -> dict:
    groups = {"train": [], "val": [], "test": []}
    for ar, sp in assign.items():
        groups[sp].append(ar)

    def pos_ars(split, key):
        return [ar for ar in groups[split] if stats[ar][key] > 0]

    def pos_frames(split, key):
        return sum(stats[ar][key] for ar in groups[split])

    failures = []
    n_x_val = len(pos_ars("val", "x24"))
    n_x_test = len(pos_ars("test", "x24"))
    n_m5_val = len(pos_ars("val", "m5"))
    n_m5_test = len(pos_ars("test", "m5"))
    if n_x_val < MIN_POS_ARS["X"]:
        failures.append("val X pos ARs {} < {}".format(n_x_val, MIN_POS_ARS["X"]))
    if n_x_test < MIN_POS_ARS["X"]:
        failures.append("test X pos ARs {} < {}".format(n_x_test, MIN_POS_ARS["X"]))
    if n_m5_val < MIN_POS_ARS["M5"]:
        failures.append("val M5 pos ARs {} < {}".format(n_m5_val, MIN_POS_ARS["M5"]))
    if n_m5_test < MIN_POS_ARS["M5"]:
        failures.append("test M5 pos ARs {} < {}".format(n_m5_test, MIN_POS_ARS["M5"]))

    dominance = {}
    ratios = {}
    for name, key in TASKS:
        pv = pos_frames("val", key)
        pt = pos_frames("test", key)
        ratio = (pv / pt) if pt else float("inf")
        ratios[name] = {
            "val": pv,
            "test": pt,
            "ratio": None if pt == 0 else ratio,
        }
        if pt == 0 or ratio < RATIO_LO or ratio > RATIO_HI:
            failures.append(
                "{} val/test pos-frame ratio {} not in [{}, {}]".format(
                    name, "{:.3f}".format(ratio) if pt else "inf", RATIO_LO, RATIO_HI
                )
            )
        for split, total in (("val", pv), ("test", pt)):
            worst_ar = None
            worst_frac = 0.0
            if total > 0:
                for ar in groups[split]:
                    frac = stats[ar][key] / total
                    if frac > worst_frac:
                        worst_frac = frac
                        worst_ar = ar
            dominance[name + "_" + split] = {
                "ar": worst_ar,
                "frac": worst_frac,
                "frames": stats[worst_ar][key] if worst_ar else 0,
            }
            if worst_frac > ALPHA:
                failures.append(
                    "{} {} one-AR fraction {:.3f} > {}".format(
                        name, split, worst_frac, ALPHA
                    )
                )

    def series(split, field):
        return [stats[ar][field] for ar in groups[split]]

    d_flux = cohens_d(series("val", "flux_med"), series("test", "flux_med"))
    d_nl = cohens_d(series("val", "nl_med"), series("test", "nl_med"))
    if abs(d_flux) >= D_MAX:
        failures.append("|d_flux| {:.3f} >= {}".format(abs(d_flux), D_MAX))
    if abs(d_nl) >= D_MAX:
        failures.append("|d_nl| {:.3f} >= {}".format(abs(d_nl), D_MAX))

    def stratum_counts(split):
        c = defaultdict(int)
        for ar in groups[split]:
            c[stats[ar]["stratum"]] += 1
        return {k: c[k] for k in STRATUM_ORDER}

    x_val_flux = [stats[ar]["flux_med"] for ar in pos_ars("val", "x24")]
    x_test_flux = [stats[ar]["flux_med"] for ar in pos_ars("test", "x24")]
    x_val_nl = [stats[ar]["nl_med"] for ar in pos_ars("val", "x24")]
    x_test_nl = [stats[ar]["nl_med"] for ar in pos_ars("test", "x24")]

    report = {
        "n_ars": {k: len(v) for k, v in groups.items()},
        "n_frames": {k: sum(stats[ar]["n"] for ar in v) for k, v in groups.items()},
        "stratum": {k: stratum_counts(k) for k in groups},
        "n_pos_ars": {
            "X_val": n_x_val,
            "X_test": n_x_test,
            "M5_val": n_m5_val,
            "M5_test": n_m5_test,
        },
        "pos_frames": ratios,
        "dominance": dominance,
        "cohens_d_all_ar": {"unsigned_flux": d_flux, "nl_length": d_nl},
        "x_ar_report_only": {
            "d_flux": cohens_d(x_val_flux, x_test_flux),
            "d_nl": cohens_d(x_val_nl, x_test_nl),
            "val_flux_mean": mean(x_val_flux),
            "test_flux_mean": mean(x_test_flux),
            "val_nl_mean": mean(x_val_nl),
            "test_nl_mean": mean(x_test_nl),
            "note": "not a reject gate; n_X in val/test is small",
        },
        "failures": failures,
        "ok": len(failures) == 0,
    }
    return report


def checksum_assignment(assign: dict) -> str:
    blob = json.dumps(
        {k: assign[k] for k in sorted(assign)}, separators=(",", ":"), sort_keys=True
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def dump_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(
        description="JW-FD split-v2 rejection sampling (official seed=3970)"
    )
    parser.add_argument("--rebuild-stats", action="store_true")
    parser.add_argument("--max-tries", type=int, default=MAX_TRIES)
    parser.add_argument("--seed-start", type=int, default=SEED_START)
    parser.add_argument("--csv", type=Path, default=DEFAULT_SRC, help="full PNG label CSV")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=_HERE,
        help="write candidate JSON / AR lists here",
    )
    parser.add_argument(
        "--official-dir",
        type=Path,
        default=DEFAULT_OFFICIAL,
        help="optional extra split CSV directory",
    )
    args = parser.parse_args()

    root = args.out_dir
    src = args.csv
    stats_path = root / "ar_stats.json"
    if args.rebuild_stats or not stats_path.exists():
        print("building AR stats from", src)
        stats = build_ar_stats(src)
        dump_json(stats_path, stats)
        print("wrote", stats_path, "n_ars", len(stats))
    else:
        stats = json.loads(stats_path.read_text(encoding="utf-8"))
        print("loaded AR stats", len(stats))

    stratum_n = defaultdict(int)
    for a in stats.values():
        stratum_n[a["stratum"]] += 1
    print("strata", dict(stratum_n))

    extra = load_official_assignment(args.official_dir)
    if extra:
        extra_rep = evaluate(extra, stats)
        dump_json(
            root / "extra_split_diagnostics.json",
            {
                "checksum": checksum_assignment(extra),
                "report": extra_rep,
            },
        )
        print(
            "extra split:",
            "PASS" if extra_rep["ok"] else "FAIL",
            extra_rep["failures"][:8],
        )
    else:
        print("no extra split CSVs at", args.official_dir)

    fail_hist = defaultdict(int)
    tries = []
    winner = None
    for i in range(args.max_tries):
        seed = args.seed_start + i
        assign = assign_for_seed(seed, stats)
        # every AR assigned
        if set(assign) != set(stats):
            raise SystemExit("assignment AR set mismatch at seed {}".format(seed))
        rep = evaluate(assign, stats)
        tag = "ok" if rep["ok"] else (rep["failures"][0] if rep["failures"] else "fail")
        fail_hist[tag if rep["ok"] else "fail:" + tag.split(">")[0][:48]] += 1
        tries.append({"seed": seed, "ok": rep["ok"], "n_fail": len(rep["failures"]), "first": tag})
        if i < 15 or i % 100 == 0:
            print(
                "try", i + 1, "seed", seed, "ok" if rep["ok"] else "FAIL",
                "n_fail", len(rep["failures"]),
                (rep["failures"][0] if rep["failures"] else ""),
            )
        if rep["ok"]:
            winner = {
                "status": "awaiting_review",
                "seed": seed,
                "try_index": i + 1,
                "algorithm": "split_v2 rejection sampling",
                "constants": {
                    "TRAIN_R": TRAIN_R,
                    "VAL_R": VAL_R,
                    "MIN_TERTILE_N": MIN_TERTILE_N,
                    "MIN_POS_ARS": MIN_POS_ARS,
                    "ALPHA": ALPHA,
                    "RATIO_LO": RATIO_LO,
                    "RATIO_HI": RATIO_HI,
                    "D_MAX": D_MAX,
                    "SEED_START": args.seed_start,
                    "n_x_definition": "onsets of flare_label_X1.0_1hr; 0+X24h => X_single",
                },
                "checksum": checksum_assignment(assign),
                "assignment": {k: assign[k] for k in sorted(assign)},
                "report": rep,
            }
            break

    dump_json(root / "search_tries.json", {"fail_hist": dict(fail_hist), "tries": tries})
    if winner is None:
        dump_json(
            root / "candidate.json",
            {
                "status": "no_seed_in_range",
                "seed_start": args.seed_start,
                "max_tries": args.max_tries,
                "fail_hist": dict(fail_hist),
            },
        )
        print("NO valid seed in", args.seed_start, "..", args.seed_start + args.max_tries - 1)
        print("fail_hist", dict(fail_hist))
        return
    dump_json(root / "candidate.json", winner)
    lists = {"train": [], "val": [], "test": []}
    for ar, sp in winner["assignment"].items():
        lists[sp].append(ar)
    dump_json(
        root / "candidate_ar_lists.json",
        {k: sorted(v) for k, v in lists.items()},
    )
    print("WINNER seed", winner["seed"], "after", winner["try_index"], "tries")
    print("checksum", winner["checksum"])
    print("n_ars", winner["report"]["n_ars"])
    print("stratum val", winner["report"]["stratum"]["val"])
    print("stratum test", winner["report"]["stratum"]["test"])
    print("pos frames", winner["report"]["pos_frames"])
    print("d_flux", winner["report"]["cohens_d_all_ar"]["unsigned_flux"])
    print("d_nl", winner["report"]["cohens_d_all_ar"]["nl_length"])
    print("awaiting review: do not rewrite labels until approved")


if __name__ == "__main__":
    main()
