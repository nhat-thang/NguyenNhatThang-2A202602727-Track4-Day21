"""Data health dashboard: chạy trên 1 dataset, ghi CSV (metric + cờ cảnh báo + frame score) và ảnh dashboard.

    python -m src.dashboard --data-root data/synthetic --name synthetic
    python -m src.dashboard --data-root data/kitti_mini --name kitti
    python -m src.dashboard --data-root data/nuscenes_mini_subset --name nusc

Kết quả:
    results/health_<name>.csv              mỗi dòng 1 frame: metric, flags (lý do), status, frame_score
    results/figures/dashboard_<name>.png   8 biểu đồ
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from src.health import AZ_BIN_DEG, ELEV_BIN_DEG, INTENSITY_BINS, RANGE_BINS, analyze

STATUS_COLOR = {"OK": "#3a8f5c", "REVIEW": "#e0a030", "REJECT": "#c8433a"}


def plot_dashboard(df, hists, title: str, out: Path) -> None:
    colors = df["status"].map(STATUS_COLOR)
    x = np.arange(len(df))
    short = [f[-6:] if len(df) <= 25 else "" for f in df["frame_id"]]
    fig, axes = plt.subplots(3, 3, figsize=(18, 12))
    ax = axes.ravel()

    ax[0].bar(x, df["n_points"], color=colors)
    ax[0].axhline(df["n_points"].median(), ls="--", c="k", lw=0.8, label="median")
    ax[0].set(title="Points / frame (màu = status)", xticks=x, xticklabels=short)
    ax[0].legend()

    centers = (RANGE_BINS[:-1] + RANGE_BINS[1:]) / 2
    ax[1].plot(centers, hists["range"].T / hists["range"].sum(1), color="gray", alpha=0.4, lw=0.8)
    ax[1].plot(centers, hists["range"].sum(0) / hists["range"].sum(), color="k", lw=2, label="toàn dataset")
    ax[1].set(title="Phân bố range (mỗi đường = 1 frame)", xlabel="range xy (m)", ylabel="tỉ lệ điểm", yscale="log")
    ax[1].legend()

    ic = (INTENSITY_BINS[:-1] + INTENSITY_BINS[1:]) / 2
    ax[2].plot(ic, hists["intensity"].T / hists["intensity"].sum(1), color="gray", alpha=0.4, lw=0.8)
    ax[2].plot(ic, hists["intensity"].sum(0) / hists["intensity"].sum(), color="k", lw=2)
    ax[2].set(title="Phân bố intensity (chuẩn hoá 0–1)", xlabel="intensity", yscale="log")

    ax[3].bar(x, 100 * df["invalid_ratio"], color=colors)
    ax[3].set(title="Invalid ratio (NaN/Inf) %", xticks=x, xticklabels=short)

    az = hists["azimuth"] / np.maximum(np.median(hists["azimuth"], axis=1, keepdims=True), 1)
    im = ax[4].imshow(az, aspect="auto", cmap="viridis", vmin=0, vmax=2,
                      extent=(-180, 180, len(df) - 0.5, -0.5))
    ax[4].set(title="Mật độ theo azimuth (/ trung vị của frame)", xlabel="azimuth (deg)", ylabel="frame idx")
    fig.colorbar(im, ax=ax[4])

    el_c = np.arange(-35, 10, ELEV_BIN_DEG) + ELEV_BIN_DEG / 2
    ax[5].plot(el_c, hists["elevation"].mean(0) / hists["elevation"].mean(0).sum(), color="k")
    ax[5].set(title=f"Mật độ theo elevation (TB các frame, {df['elev_rows'].median():.0f} bin 0.25° có điểm)",
              xlabel="elevation (deg)", ylabel="tỉ lệ điểm")

    ax[6].bar(x, df["time_gap_s"].fillna(0), color=colors)
    if df["time_gap_s"].notna().any():
        ax[6].axhline(1.5 * df["time_gap_s"].median(), ls="--", c="r", lw=0.8, label="1.5 x median")
        ax[6].legend()
    else:
        ax[6].text(0.5, 0.5, "không có timestamp", ha="center", transform=ax[6].transAxes)
    ax[6].set(title="Time gap tới frame trước (s)", xticks=x, xticklabels=short)

    ax[7].bar(x, df["max_az_gap_deg"], color=colors)
    ax[7].axhline(20, ls="--", c="r", lw=0.8, label="ngưỡng 20°")
    ax[7].set(title="Cung azimuth trống dài nhất (deg)", xticks=x, xticklabels=short)
    ax[7].legend()

    ax[8].axis("off")
    counts = df["status"].value_counts().reindex(["OK", "REVIEW", "REJECT"], fill_value=0)
    lines = [f"OK={counts['OK']}  REVIEW={counts['REVIEW']}  REJECT={counts['REJECT']}", ""]
    flagged = df[df["status"] != "OK"]
    for _, r in flagged.head(14).iterrows():
        lines.append(f"{r['frame_id']} [{r['status']}] {r['flags'][:60]}")
    if len(flagged) > 14:
        lines.append(f"... +{len(flagged) - 14} frame (xem CSV)")
    ax[8].text(0, 1, "\n".join(lines), va="top", family="monospace", fontsize=8.5)
    ax[8].set_title("Frame bị gắn cờ")

    for a in (ax[0], ax[3], ax[6], ax[7]):
        a.tick_params(axis="x", rotation=90, labelsize=7)
    fig.suptitle(title, fontsize=14)
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=90)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description="Data health dashboard cho LiDAR: metric từng frame, cờ cảnh báo, frame score")
    ap.add_argument("--data-root", default="data/synthetic", help="thư mục KITTI hoặc nuScenes")
    ap.add_argument("--name", default=None, help="tên ngắn dùng trong tên file kết quả (mặc định: tên thư mục)")
    ap.add_argument("--out-dir", default="results", help="thư mục ghi CSV; ảnh ghi vào <out-dir>/figures")
    args = ap.parse_args()

    name = args.name or Path(args.data_root).name
    df, hists = analyze(args.data_root)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_dir / f"health_{name}.csv", index=False, float_format="%.5g")
    plot_dashboard(df, hists, f"Data health — {args.data_root} ({len(df)} frame)",
                   out_dir / "figures" / f"dashboard_{name}.png")
    print(df[["frame_id", "n_points", "az_coverage", "max_az_gap_deg", "time_gap_s", "status", "flags",
              "frame_score"]].to_string(index=False, max_colwidth=70))
    print(f"-> {out_dir / f'health_{name}.csv'}, {out_dir / 'figures' / f'dashboard_{name}.png'}")


if __name__ == "__main__":
    main()
