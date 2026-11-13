# -*- coding: utf-8 -*-
"""Compare Step2 anchor centroids at search radii 80 and 250 pixels.

Replays the published anchor choice (first SRS Stonyhurst point, Carrington
track, frame nearest central meridian) and only changes the centroid window.
Does not rewrite any cropped FITS.
"""

import glob
import json
import os
import re
from collections import defaultdict

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from astropy.coordinates import SkyCoord
from astropy.time import Time
import astropy.units as u
from matplotlib.patches import Rectangle
from scipy.ndimage import center_of_mass, label
import sunpy.map
from sunpy.coordinates import frames

SRS_ROOT = "/data/Datasets/Labels"
FITS_ROOT = "/data/Datasets/Fits/HMI"
CROP_ROOT = "/data/Datasets/JW-FD/fits_600"
OUT_DIR = os.path.dirname(os.path.abspath(__file__))
FIG_DIR = os.path.join(OUT_DIR, "figures")

THRESH_G = 100.0
RADII = (80, 250)
CROP = 300
VIEW = 560
BULK_R = 500
REJECT_PX = 150.0


def parse_location(loc_str):
    if not isinstance(loc_str, str) or len(loc_str) < 6:
        return None, None
    try:
        lat = float(loc_str[1:3]) * (1 if loc_str[0] == "N" else -1)
        lon = float(loc_str[4:]) * (-1 if loc_str[3] == "E" else 1)
        return lat, lon
    except ValueError:
        return None, None


def srs_folders():
    found = []
    for year in range(2011, 2026):
        for path in (
            f"{SRS_ROOT}/{year}/{year}_SRS",
            f"{SRS_ROOT}/{year}_SRS",
        ):
            if os.path.isdir(path):
                found.append(path)
                break
    return found


def load_srs():
    """Spotted-region rows only. Same stop rule as step2 (blank line or IA/II)."""
    appearances = defaultdict(list)
    by_date = defaultdict(list)
    for folder in srs_folders():
        for path in sorted(glob.glob(os.path.join(folder, "*.txt"))):
            match = re.search(r"(\d{8})", os.path.basename(path))
            if not match:
                continue
            date = match.group(1)
            in_table = False
            with open(path, "r", errors="replace") as handle:
                for line in handle:
                    if "Nmbr" in line and "Location" in line:
                        in_table = True
                        continue
                    if not in_table:
                        continue
                    if line.strip() == "" or "IA" in line or "II" in line:
                        break
                    parts = line.split()
                    if len(parts) < 7:
                        continue
                    lat, lon = parse_location(parts[1])
                    if lat is None:
                        continue
                    try:
                        area = int(parts[3])
                        extent = int(parts[5])
                    except ValueError:
                        continue
                    row = {
                        "nmbr": parts[0],
                        "date": date,
                        "lat": lat,
                        "lon": lon,
                        "area": area,
                        "ll": extent,
                    }
                    appearances[parts[0]].append(row)
                    by_date[date].append(row)
    return appearances, by_date


def angular_sep(lat1, lon1, lat2, lon2):
    dlat = lat2 - lat1
    dlon = (lon2 - lon1 + 180.0) % 360.0 - 180.0
    scale = np.cos(np.deg2rad(0.5 * (lat1 + lat2)))
    return float(np.hypot(dlat, dlon * scale))


def filename_time(path):
    match = re.search(r"(\d{8})_(\d{6})", os.path.basename(path))
    if not match:
        return None
    day, clock = match.group(1), match.group(2)
    stamp = (
        f"{day[:4]}-{day[4:6]}-{day[6:8]}T"
        f"{clock[:2]}:{clock[2:4]}:{clock[4:6]}"
    )
    return Time(stamp, scale="tai")


def fits_for_dates(dates):
    files = []
    for date in dates:
        year, month = date[:4], date[4:6]
        folder = f"{FITS_ROOT}/{year}_with_headers/{month}"
        files.extend(
            glob.glob(folder + f"/hmi.m_720s.{date}_*_TAI.*.magnetogram.fits")
        )
    return sorted(files)


def choose_anchor(lat, lon, fits_paths):
    """Same frame choice as process_single_ar_anchor, using filename TAI times."""
    first = filename_time(fits_paths[0])
    p_stony = SkyCoord(
        lon=lon * u.deg,
        lat=lat * u.deg,
        frame=frames.HeliographicStonyhurst(obstime=first),
    )
    p_carr = p_stony.transform_to(
        frames.HeliographicCarrington(obstime=first, observer="earth")
    )
    carr_lon = float(p_carr.lon.deg)
    carr_lat = float(p_carr.lat.deg)
    stride = max(1, len(fits_paths) // 20)
    best_path, best_abs = None, 999.0
    for path in fits_paths[::stride]:
        obstime = filename_time(path)
        pc = SkyCoord(
            lon=carr_lon * u.deg,
            lat=carr_lat * u.deg,
            frame=frames.HeliographicCarrington(obstime=obstime, observer="earth"),
        )
        cur = float(
            pc.transform_to(frames.HeliographicStonyhurst(obstime=obstime)).lon.deg
        )
        if abs(cur) < best_abs:
            best_abs, best_path = abs(cur), path
        if best_abs < 5:
            break
    if best_path is None:
        best_path = fits_paths[len(fits_paths) // 2]
    return best_path, carr_lon, carr_lat, best_abs


def centroid_in_window(data, cx, cy, radius, thresh):
    ny, nx = data.shape
    y0, y1 = max(0, cy - radius), min(ny, cy + radius)
    x0, x1 = max(0, cx - radius), min(nx, cx + radius)
    sub = np.nan_to_num(data[y0:y1, x0:x1])
    weight = np.abs(sub) * (np.abs(sub) > thresh)
    if np.count_nonzero(weight) == 0:
        return None
    dy, dx = center_of_mass(weight)
    return float(x0 + dx), float(y0 + dy), int(np.count_nonzero(weight))


def component_centroid(data, cx, cy, radius, thresh):
    """COM of the |B|>thresh component nearest the SRS pixel, inside the window."""
    ny, nx = data.shape
    y0, y1 = max(0, cy - radius), min(ny, cy + radius)
    x0, x1 = max(0, cx - radius), min(nx, cx + radius)
    sub = np.nan_to_num(data[y0:y1, x0:x1])
    mask = np.abs(sub) > thresh
    if not np.any(mask):
        return None
    labels, nlab = label(mask)
    cy_l = int(np.clip(cy - y0, 0, mask.shape[0] - 1))
    cx_l = int(np.clip(cx - x0, 0, mask.shape[1] - 1))
    # Nearest strong pixel to the SRS point decides the component.
    ys, xs = np.nonzero(mask)
    nearest = np.argmin((ys - cy_l) ** 2 + (xs - cx_l) ** 2)
    chosen = labels[ys[nearest], xs[nearest]]
    weight = np.abs(sub) * (labels == chosen)
    dy, dx = center_of_mass(weight)
    return float(x0 + dx), float(y0 + dy), int(np.count_nonzero(labels == chosen))


def project(hmi_map, lat, lon, carr=False, carr_lon=None, carr_lat=None):
    if carr:
        coord = SkyCoord(
            lon=carr_lon * u.deg,
            lat=carr_lat * u.deg,
            frame=frames.HeliographicCarrington(
                obstime=hmi_map.date, observer="earth"
            ),
        )
    else:
        coord = SkyCoord(
            lon=lon * u.deg,
            lat=lat * u.deg,
            frame=frames.HeliographicStonyhurst(obstime=hmi_map.date),
        )
    pix = hmi_map.world_to_pixel(coord)
    return float(pix.x.value), float(pix.y.value)


def bulk_center(data, cx, cy, others):
    """|B|>100 centroid inside ±BULK_R, dropping pixels closer to another AR."""
    ny, nx = data.shape
    y0, y1 = max(0, int(cy) - BULK_R), min(ny, int(cy) + BULK_R)
    x0, x1 = max(0, int(cx) - BULK_R), min(nx, int(cx) + BULK_R)
    sub = np.nan_to_num(data[y0:y1, x0:x1])
    yy, xx = np.mgrid[y0:y1, x0:x1]
    dist2 = (xx - cx) ** 2 + (yy - cy) ** 2
    owned = np.ones(sub.shape, dtype=bool)
    for ox, oy in others:
        owned &= dist2 <= (xx - ox) ** 2 + (yy - oy) ** 2
    weight = np.abs(sub) * ((np.abs(sub) > THRESH_G) & owned)
    if np.count_nonzero(weight) == 0:
        return None, None
    dy, dx = center_of_mass(weight)
    return float(x0 + dx), float(y0 + dy), weight, (x0, y0)


def flux_fraction(weight, origin, center):
    if weight is None:
        return None
    x0, y0 = origin
    yy, xx = np.mgrid[0 : weight.shape[0], 0 : weight.shape[1]]
    xx = xx + x0
    yy = yy + y0
    inside = (np.abs(xx - center[0]) <= CROP) & (np.abs(yy - center[1]) <= CROP)
    total = float(weight.sum())
    if total <= 0:
        return None
    return float(weight[inside].sum() / total)


def draw(path, data, info, markers, boxes, neighbors):
    cx, cy = info["rough"]
    x0 = max(0, int(cx) - VIEW)
    x1 = min(data.shape[1], int(cx) + VIEW)
    y0 = max(0, int(cy) - VIEW)
    y1 = min(data.shape[0], int(cy) + VIEW)
    cut = np.nan_to_num(data[y0:y1, x0:x1])
    fig, ax = plt.subplots(figsize=(7.4, 7.6))
    ax.imshow(
        cut,
        cmap="gray",
        vmin=-800,
        vmax=800,
        origin="lower",
        extent=(x0 - 0.5, x1 - 0.5, y0 - 0.5, y1 - 0.5),
    )
    styles = {
        "r80": ("#1f77b4", "600 box @ ±80"),
        "r250": ("#ff7f0e", "600 box @ ±250"),
    }
    for key, (color, label) in styles.items():
        x, y = boxes[key]
        ax.add_patch(
            Rectangle(
                (x - CROP, y - CROP),
                2 * CROP,
                2 * CROP,
                fill=False,
                edgecolor=color,
                linewidth=1.3,
                label=label,
            )
        )
        ax.plot(x, y, marker="+", color=color, markersize=12, markeredgewidth=1.6)
    ax.plot(cx, cy, marker="o", color="white", markersize=7, markerfacecolor="none",
            markeredgewidth=1.3, label="SRS track point")
    for nx_, ny_, name, sep in neighbors:
        if x0 <= nx_ <= x1 and y0 <= ny_ <= y1:
            ax.plot(nx_, ny_, marker="^", color="#d62728", markersize=6)
            ax.text(nx_ + 8, ny_ + 8, f"{name} {sep:.1f}°", color="#d62728", fontsize=8)
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_xlabel("pixel x")
    ax.set_ylabel("pixel y")
    ax.set_title(info["title"], fontsize=10)
    ax.legend(loc="upper right", fontsize=8, framealpha=0.85)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def select(appearances, by_date):
    rows = []
    for nmbr, rows_ar in appearances.items():
        if not os.path.isdir(os.path.join(CROP_ROOT, nmbr)):
            continue
        if len(rows_ar) < 4:
            continue
        cm = min(rows_ar, key=lambda r: abs(r["lon"]))
        if abs(cm["lon"]) > 30:
            continue
        nearest, nearest_id = 999.0, None
        for other in by_date[cm["date"]]:
            if other["nmbr"] == nmbr:
                continue
            sep = angular_sep(cm["lat"], cm["lon"], other["lat"], other["lon"])
            if sep < nearest:
                nearest, nearest_id = sep, other["nmbr"]
        rows.append(
            {
                "nmbr": nmbr,
                "max_area": max(r["area"] for r in rows_ar),
                "max_ll": max(r["ll"] for r in rows_ar),
                "cm": cm,
                "sep": nearest,
                "neighbor": nearest_id,
                "first": min(rows_ar, key=lambda r: r["date"]),
                "dates": sorted({r["date"] for r in rows_ar}),
                "by_date": {r["date"]: r for r in rows_ar},
            }
        )
    large = [r for r in rows if r["max_area"] >= 800 or r["max_ll"] >= 10]
    small = [r for r in rows if 15 <= r["max_area"] <= 80 and r["max_ll"] <= 5]
    large.sort(key=lambda r: -r["max_area"])
    small.sort(key=lambda r: r["max_area"])

    def take(pool, n, crowded, relax):
        picked, years = [], set()
        limit = 7.0 if crowded else 12.0
        for prefer_new in (True, False):
            for row in pool:
                if len(picked) >= n:
                    break
                ok = row["sep"] < limit if crowded else row["sep"] > limit
                if not ok and relax:
                    ok = row["sep"] < 10 if crowded else row["sep"] > 8
                if not ok:
                    continue
                if any(p["nmbr"] == row["nmbr"] for p in picked):
                    continue
                year = row["cm"]["date"][:4]
                if prefer_new and year in years:
                    continue
                picked.append(row)
                years.add(year)
        return picked

    chosen = []
    for row in (
        take(large, 3, False, False)
        + take(large, 2, True, True)
        + take(small, 3, False, False)
        + take(small, 2, True, True)
    ):
        row["group"] = (
            "large" if row["max_area"] >= 800 or row["max_ll"] >= 10 else "small"
        )
        row["crowded"] = row["sep"] < 10
        chosen.append(row)
    return chosen


def main():
    os.makedirs(FIG_DIR, exist_ok=True)
    print("reading SRS...", flush=True)
    appearances, by_date = load_srs()
    chosen = select(appearances, by_date)
    print(f"selected {len(chosen)} ARs", flush=True)
    results = []
    for row in chosen:
        first = row["first"]
        fits_paths = fits_for_dates(row["dates"])
        if len(fits_paths) < 5:
            print(f"AR{row['nmbr']}: too few FITS ({len(fits_paths)})", flush=True)
            continue
        anchor, carr_lon, carr_lat, anchor_lon = choose_anchor(
            first["lat"], first["lon"], fits_paths
        )
        print(
            f"AR{row['nmbr']} group={row['group']} area={row['max_area']} "
            f"LL={row['max_ll']} sep={row['sep']:.1f} anchor_lon={anchor_lon:.1f} "
            f"{os.path.basename(anchor)}",
            flush=True,
        )
        try:
            hmi_map = sunpy.map.Map(anchor, memmap=False)
            data = np.array(hmi_map.data, dtype=np.float64)
        except Exception as exc:
            print(f"  skip AR{row['nmbr']}: {exc}", flush=True)
            continue
        rx, ry = project(
            hmi_map, None, None, carr=True, carr_lon=carr_lon, carr_lat=carr_lat
        )
        cx, cy = int(rx), int(ry)
        date = re.search(r"(\d{8})", os.path.basename(anchor)).group(1)
        others = []
        neighbor_draw = []
        nearest_px, nearest_name, nearest_deg = 1e9, None, None
        for other in by_date.get(date, []):
            if other["nmbr"] == row["nmbr"]:
                continue
            ox, oy = project(hmi_map, other["lat"], other["lon"])
            others.append((ox, oy))
            dist = float(np.hypot(ox - cx, oy - cy))
            sep = angular_sep(row["by_date"].get(date, row["cm"])["lat"],
                              row["by_date"].get(date, row["cm"])["lon"],
                              other["lat"], other["lon"])
            if dist < nearest_px:
                nearest_px, nearest_name, nearest_deg = dist, other["nmbr"], sep
            if dist < 700:
                neighbor_draw.append((ox, oy, other["nmbr"], sep))
        centers = {}
        counts = {}
        for radius in RADII:
            got = centroid_in_window(data, cx, cy, radius, THRESH_G)
            if got is None:
                centers[radius] = (float(cx), float(cy))
                counts[radius] = 0
            else:
                centers[radius] = (got[0], got[1])
                counts[radius] = got[2]
        cc = component_centroid(data, cx, cy, 250, THRESH_G)
        bulk = bulk_center(data, cx, cy, others)
        if bulk[0] is None:
            bulk_xy, weight, origin = None, None, None
        else:
            bulk_xy, weight, origin = (bulk[0], bulk[1]), bulk[2], bulk[3]
        shifts = {
            radius: float(np.hypot(centers[radius][0] - cx, centers[radius][1] - cy))
            for radius in RADII
        }
        to_bulk = {}
        fractions = {}
        for radius in RADII:
            if bulk_xy is None:
                to_bulk[radius] = None
                fractions[radius] = None
            else:
                to_bulk[radius] = float(
                    np.hypot(centers[radius][0] - bulk_xy[0], centers[radius][1] - bulk_xy[1])
                )
                fractions[radius] = flux_fraction(weight, origin, centers[radius])
        cc_shift = None
        if cc is not None:
            cc_shift = float(np.hypot(cc[0] - centers[250][0], cc[1] - centers[250][1]))
        today = row["by_date"].get(date)
        srs_today_px = None
        if today is not None:
            sx, sy = project(hmi_map, today["lat"], today["lon"])
            srs_today_px = float(np.hypot(sx - cx, sy - cy))
        info = {
            "nmbr": row["nmbr"],
            "group": row["group"],
            "crowded": bool(row["crowded"]),
            "max_area": row["max_area"],
            "max_ll": row["max_ll"],
            "cm_date": row["cm"]["date"],
            "cm_sep_deg": round(row["sep"], 2),
            "cm_neighbor": row["neighbor"],
            "anchor": os.path.basename(anchor),
            "anchor_abs_lon": round(anchor_lon, 2),
            "rough_xy": [cx, cy],
            "center_80": [round(centers[80][0], 2), round(centers[80][1], 2)],
            "center_250": [round(centers[250][0], 2), round(centers[250][1], 2)],
            "shift_80_px": round(shifts[80], 1),
            "shift_250_px": round(shifts[250], 1),
            "delta_px": round(
                float(np.hypot(centers[250][0] - centers[80][0], centers[250][1] - centers[80][1])),
                1,
            ),
            "reject_250": shifts[250] > REJECT_PX,
            "npix_80": counts[80],
            "npix_250": counts[250],
            "dist_bulk_80": None if to_bulk[80] is None else round(to_bulk[80], 1),
            "dist_bulk_250": None if to_bulk[250] is None else round(to_bulk[250], 1),
            "flux_frac_80": None if fractions[80] is None else round(fractions[80], 3),
            "flux_frac_250": None if fractions[250] is None else round(fractions[250], 3),
            "cc_vs_250_px": None if cc_shift is None else round(cc_shift, 1),
            "nearest_px": None if nearest_name is None else round(nearest_px, 1),
            "nearest_deg": None if nearest_deg is None else round(nearest_deg, 2),
            "nearest_nmbr": nearest_name,
            "srs_today_vs_track_px": None if srs_today_px is None else round(srs_today_px, 1),
            "cdelt": float(hmi_map.scale.axis1.value),
        }
        title = (
            f"AR{row['nmbr']}  {row['group']}  area {row['max_area']}  LL {row['max_ll']}°\n"
            f"shift ±80 {info['shift_80_px']:.0f}px   ±250 {info['shift_250_px']:.0f}px"
            f"   nearest AR{nearest_name} {0 if nearest_deg is None else nearest_deg:.1f}°"
        )
        fig_path = os.path.join(FIG_DIR, f"AR{row['nmbr']}.png")
        draw(
            fig_path,
            data,
            {"rough": (cx, cy), "title": title},
            {},
            {"r80": centers[80], "r250": centers[250]},
            neighbor_draw,
        )
        info["figure"] = os.path.relpath(fig_path, OUT_DIR)
        results.append(info)
        print(
            f"  shift80={info['shift_80_px']} shift250={info['shift_250_px']} "
            f"delta={info['delta_px']} reject={info['reject_250']} "
            f"bulk80={info['dist_bulk_80']} bulk250={info['dist_bulk_250']} "
            f"frac80={info['flux_frac_80']} frac250={info['flux_frac_250']}",
            flush=True,
        )
        del hmi_map, data
    out_json = os.path.join(OUT_DIR, "summary.json")
    with open(out_json, "w") as handle:
        json.dump(results, handle, indent=2)
    print(f"wrote {out_json} ({len(results)} ARs)", flush=True)


if __name__ == "__main__":
    main()
