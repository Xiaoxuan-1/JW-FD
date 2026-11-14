"""GOES 1-8 A flares from the SWPC edited event lists (YYYYMMDDevents.txt).

One XRA line per flare:

  #Event    Begin    Max       End  Obs  Q  Type  Loc/Frq   Particulars       Reg#
  1160 +     0010   0013      0022  G16  5   XRA  1-8A      M1.3    9.6E-03   3664
  5920       0420   0426      0429  G15  5   XRA  1-8A      X1.1    2.8E-02   1890

'+' after the event number only marks related reports and says nothing about
whether the flare happened. Times are UT on the file's date and may carry a B
(before), A (after) or U (uncertain) prefix or be '////'. Max and End roll over
to the next day when they are earlier than Begin. Reg# (NOAA number mod 10000)
is blank for flares not assigned to a region.
"""
from __future__ import annotations

import glob
import os
import re
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

LINE = re.compile(
    r"^\s*(?P<event>\d+)\s*(?P<plus>\+)?\s+"
    r"(?P<begin>[ABU]?\d{4}|////)\s+(?P<max>[ABU]?\d{4}|////)\s+(?P<end>[ABU]?\d{4}|////)\s+"
    r"(?P<obs>\S+)\s+(?P<q>\S+)\s+XRA\s+(?P<loc>\S+)\s+"
    r"(?P<cls>[ABCMX]\d+(?:\.\d+)?)(?:\s+(?P<flux>[\d.]+E[-+]?\d+))?(?:\s+(?P<reg>\d{4}))?\s*$"
)
_FILE_DATE = re.compile(r"(\d{8})events\.txt$")
_SCALE = {"A": 1e-8, "B": 1e-7, "C": 1e-6, "M": 1e-5, "X": 1e-4}


def class_flux(cls: str) -> float:
    return _SCALE[cls[0]] * float(cls[1:])


def _clock(day: datetime, token: str) -> Optional[datetime]:
    if token == "////":
        return None
    hhmm = re.sub(r"\D", "", token)
    return day + timedelta(hours=int(hhmm[:2]), minutes=int(hhmm[2:]))


def parse_file(path: str) -> tuple[list[dict], int]:
    """XRA records of one event list and the number of XRA lines that did not parse."""
    day = datetime.strptime(_FILE_DATE.search(path).group(1), "%Y%m%d")
    out, bad = [], 0
    with open(path, encoding="latin-1") as f:
        for line in f:
            if " XRA " not in line or line.startswith(("#", ":")):
                continue
            m = LINE.match(line.rstrip("\n"))
            if m is None:
                bad += 1
                continue
            begin, peak, end = (_clock(day, m.group(k)) for k in ("begin", "max", "end"))
            begin_from = "begin"
            if begin is None:
                begin, begin_from = (peak, "max") if peak is not None else (end, "end")
            if begin is None:
                bad += 1
                continue
            if peak is not None and peak < begin:
                peak += timedelta(days=1)
            if end is not None and end < begin:
                end += timedelta(days=1)
            out.append({
                "begin": begin, "max": peak, "end": end, "cls": m.group("cls"),
                "reg": m.group("reg") or "", "event": int(m.group("event")), "plus": m.group("plus") == "+",
                "obs": m.group("obs"), "q": m.group("q"), "loc": m.group("loc"), "flux": m.group("flux") or "",
                "begin_qualifier": m.group("begin")[0] if m.group("begin")[0] in "ABU" else "",
                "begin_from": begin_from, "source": os.path.basename(path),
            })
    return out, bad


def event_files(root: str, years) -> list[str]:
    files = []
    for y in years:
        files += glob.glob(os.path.join(root, str(y), f"{y}_events", "*events.txt"))
    return sorted(set(files))


def load_xra(root: str, years) -> tuple[pd.DataFrame, dict]:
    """Deduplicated XRA flares. Year folders overlap by a few days, and a flare
    reported twice for the same region within one minute is kept once, at its
    largest class."""
    recs, bad, files = [], 0, event_files(root, years)
    for path in files:
        r, b = parse_file(path)
        recs += r
        bad += b
    df = pd.DataFrame(recs)
    n_lines = len(df)
    df = df.drop_duplicates(["begin", "cls", "reg", "obs"]).copy()
    n_exact = n_lines - len(df)
    df["flux_cls"] = df["cls"].map(class_flux)
    df = df.sort_values(["reg", "begin", "flux_cls"], ascending=[True, True, False]).reset_index(drop=True)
    gap = df.groupby("reg")["begin"].diff()
    group = ((gap.isna()) | (gap > pd.Timedelta(minutes=1)) | (df["reg"] == "")).cumsum()
    keep = df.groupby(group)["flux_cls"].idxmax()
    n_near = len(df) - len(keep)
    df = df.loc[keep].sort_values("begin").reset_index(drop=True)
    stats = {"files": len(files), "xra_lines": n_lines, "unparsed_lines": bad,
             "exact_duplicates": n_exact, "near_duplicates": n_near, "flares": len(df)}
    return df, stats
