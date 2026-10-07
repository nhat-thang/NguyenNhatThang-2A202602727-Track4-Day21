"""CP3: dashboard có phát hiện được degradation không? Sweep 3 kiểu x nhiều mức, trên KITTI và nuScenes.

Mỗi cấu hình làm xấu MỌI frame của log (lỗi kéo dài, ví dụ bùn bám, mưa), rồi chạy cùng bộ rule với 2 kiểu baseline:
  - self  : baseline = trung vị của chính log đang kiểm tra (không có log sạch để so)
  - clean : baseline = trung vị của log sạch cùng sensor (`make_baseline` trên dữ liệu gốc)
Metric: detect_rate = % frame có status khác OK. Ở mức 0 (dữ liệu gốc) detect_rate chính là tỉ lệ báo nhầm.

    python -m src.degradation_sweep
    python -m src.degradation_sweep --datasets data/kitti_mini --seed 0
"""
from __future__ import annotations

import argparse
import zlib
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from starter.perturb import random_dropout, range_dropout, sector_dropout
from src.health import analyze, make_baseline

def sector_attenuation(points: np.ndarray, keep_ratio: float, seed: int,
                       az_start_deg: float = 30.0, width_deg: float = 40.0) -> np.ndarray:
    """Che MỘT PHẦN cung azimuth (bùn/nước bám kính LiDAR): trong cung chỉ giữ ngẫu nhiên keep_ratio điểm."""
    az = np.degrees(np.arctan2(points[:, 1], points[:, 0]))
    in_sector = (az >= az_start_deg) & (az <= az_start_deg + width_deg)
    keep = np.random.default_rng(seed).random(len(points)) < keep_ratio
    return points[~in_sector | keep]


SWEEP = {
    # tên: (danh sách mức, hàm (points, level, seed) -> points, đơn vị)
    "random_dropout": ([1.0, 0.9, 0.8, 0.7, 0.5, 0.3],
                       lambda p, lv, s: random_dropout(p, keep_ratio=lv, seed=s), "keep ratio"),
    "sector_dropout": ([0, 10, 20, 30, 45, 90],
                       lambda p, lv, s: sector_dropout(p, 30.0, 30.0 + lv) if lv else p, "độ rộng cung (deg)"),
    "sector_attenuation_40deg": ([1.0, 0.7, 0.5, 0.3, 0.1],
                                 lambda p, lv, s: sector_attenuation(p, lv, s), "keep ratio trong cung 40°"),
    "range_dropout": ([1000, 70, 50, 30, 20],
                      lambda p, lv, s: range_dropout(p, max_range_m=lv), "max range (m)"),
}


def run(datasets: list[str], seed: int) -> pd.DataFrame:
    rows = []
    for root in datasets:
        cache: dict = {}
        clean_df, clean_hists = analyze(root, cache=cache)
        clean_base = make_baseline(clean_df, clean_hists)
        for kind, (levels, fn, _) in SWEEP.items():
            for lv in levels:
                # seed riêng cho từng frame nhưng cố định: chạy lại ra đúng cùng số
                pfn = (lambda p, fid, lv=lv, fn=fn: fn(p, lv, seed + zlib.crc32(fid.encode()) % 10_000))
                for mode, base in (("self", None), ("clean", clean_base)):
                    df, _ = analyze(root, points_fn=pfn, baseline=base, cache=cache)
                    rows.append({
                        "dataset": Path(root).name, "perturb": kind, "level": lv, "baseline": mode,
                        "n_frames": len(df),
                        "detect_rate": round((df["status"] != "OK").mean(), 4),
                        "reject_rate": round((df["status"] == "REJECT").mean(), 4),
                        "n_points_ratio": round(df["n_points"].median() / clean_base["n_points"], 4),
                        "max_az_gap_deg_p50": df["max_az_gap_deg"].median(),
                        "range_p95_m": round(df["range_p95"].median(), 2),
                        "top_flag": df["flags"].str.split(" ").str[0].replace("", "-").mode()[0],
                    })
                print(f"{Path(root).name:22s} {kind:15s} {lv:>6} -> self={rows[-2]['detect_rate']:.0%} "
                      f"clean={rows[-1]['detect_rate']:.0%} ({rows[-1]['top_flag']})")
    return pd.DataFrame(rows)


def plot(df: pd.DataFrame, out: Path) -> None:
    fig, axes = plt.subplots(1, len(SWEEP), figsize=(20, 4.5))
    styles = {("kitti_mini", "clean"): ("#1f6fb4", "-", "o"), ("kitti_mini", "self"): ("#1f6fb4", ":", "x"),
              ("nuscenes_mini_subset", "clean"): ("#d0602a", "-", "o"),
              ("nuscenes_mini_subset", "self"): ("#d0602a", ":", "x")}
    for ax, (kind, (levels, _, unit)) in zip(axes, SWEEP.items()):
        sub = df[df["perturb"] == kind]
        for (ds, mode), g in sub.groupby(["dataset", "baseline"]):
            c, ls, m = styles.get((ds, mode), ("gray", "-", "."))
            ax.plot(range(len(g)), 100 * g["detect_rate"], color=c, ls=ls, marker=m,
                    label=f"{ds.split('_')[0]} / baseline={mode}")
        ax.set_xticks(range(len(levels)), [str(lv) if lv not in (1000, 0, 1.0) else f"gốc" for lv in levels])
        ax.set(title=kind, xlabel=unit, ylabel="% frame bị gắn cờ", ylim=(-5, 105))
        ax.grid(alpha=0.3)
    axes[0].legend(fontsize=8)
    fig.suptitle("Dashboard phát hiện degradation kéo dài: baseline từ log sạch vs từ chính log", fontsize=12)
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=100)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description="Sweep degradation x mức, đo % frame bị dashboard gắn cờ")
    ap.add_argument("--datasets", nargs="+", default=["data/kitti_mini", "data/nuscenes_mini_subset"])
    ap.add_argument("--seed", type=int, default=0, help="seed gốc cho random_dropout")
    ap.add_argument("--out", default="results/degradation_sweep.csv")
    args = ap.parse_args()

    df = run(args.datasets, args.seed)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    plot(df, out.parent / "figures" / "degradation_sweep.png")
    print(f"-> {out}, {out.parent / 'figures' / 'degradation_sweep.png'}")


if __name__ == "__main__":
    main()
