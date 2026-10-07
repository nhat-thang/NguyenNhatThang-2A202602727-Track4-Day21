"""CP4: vẽ 2 failure case của rule SECTOR_GAP.

fail_01: rule v1 (so bin azimuth với trung vị của CHÍNH frame) báo nhầm synthetic 000004:
         cung thưa là bóng của bức tường gần (do cảnh), không phải sensor bị che.
fail_02: rule v2 với self-baseline bị mù trước lỗi kéo dài: che 70% điểm trong cung 40° trên MỌI frame
         KITTI -> profile tham chiếu cũng bị che -> 0% frame bị gắn cờ. Baseline từ log sạch bắt được.

    python -m src.failure_cases
"""
from __future__ import annotations

import argparse
import zlib
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Wedge

from starter.datasets import list_frames, load_points
from src.degradation_sweep import sector_attenuation
from src.health import AZ_BIN_DEG, LOW_BIN_FRAC, azimuth_profile, longest_circular_run

AZ_CENTERS = np.arange(-180, 180, AZ_BIN_DEG) + AZ_BIN_DEG / 2


def clean_xyz(points: np.ndarray) -> np.ndarray:
    return points[np.isfinite(points).all(axis=1), :3]


def bev(ax, xyz, title, wedges=(), lim=40):
    ax.scatter(xyz[:, 0], xyz[:, 1], s=0.3, c=np.clip(xyz[:, 2], -2, 2), cmap="viridis")
    for (a0, a1, color, label) in wedges:
        ax.add_patch(Wedge((0, 0), lim * 1.4, a0, a1, color=color, alpha=0.18, label=label))
    ax.plot(0, 0, "r^", ms=8)
    ax.set(xlim=(-lim / 2, lim), ylim=(-lim * 0.75, lim * 0.75), aspect="equal", title=title,
           xlabel="x (m, phía trước)", ylabel="y (m, bên trái)")
    if wedges:
        ax.legend(loc="lower right", fontsize=8)


def run_wedge(low: np.ndarray, color: str, label: str):
    n, start = longest_circular_run(low)
    a0 = -180 + start * AZ_BIN_DEG
    return (a0, a0 + n * AZ_BIN_DEG, color, f"{label}: {n * AZ_BIN_DEG:.0f}°")


def fail_01(out: Path) -> None:
    root = "data/synthetic"
    hists = np.array([azimuth_profile(clean_xyz(load_points(root, f))) for f in list_frames(root)])
    fid, i = "000004", list_frames(root).index("000004")
    h = hists[i]
    ratio_v1 = h / np.median(h)                       # v1: so với trung vị của chính frame
    ratio_v2 = h / np.median(hists, axis=0)           # v2: so với profile tham chiếu (cùng bin, mọi frame)
    low_v1, low_v2 = ratio_v1 < LOW_BIN_FRAC, ratio_v2 < LOW_BIN_FRAC

    fig, ax = plt.subplots(1, 2, figsize=(16, 6))
    wedges = [run_wedge(low_v1, "red", "rule v1 gắn cờ SECTOR_GAP")]
    bev(ax[0], clean_xyz(load_points(root, fid)), f"synthetic {fid} — BEV (màu = z). Cung đỏ: v1 báo 'sensor bị che'",
        wedges)
    ax[0].annotate("tường bên trái (y ≈ 9 m) chắn mọi điểm phía sau\n-> ở 40°–65° chỉ còn điểm < 15 m",
                   xy=(9, 9.3), xytext=(12, 22),
                   arrowprops=dict(arrowstyle="->"), fontsize=10)
    ax[1].plot(AZ_CENTERS, ratio_v1, "r-", label="v1: bin / trung vị của chính frame")
    ax[1].plot(AZ_CENTERS, ratio_v2, "b-", label="v2: bin / trung vị cùng bin trên mọi frame")
    ax[1].axhline(LOW_BIN_FRAC, c="k", ls="--", lw=0.8, label=f"ngưỡng {LOW_BIN_FRAC}")
    ax[1].fill_between(AZ_CENTERS, 0, 2.5, where=low_v1, color="red", alpha=0.15, step="mid")
    ax[1].set(xlabel="azimuth (deg)", ylabel="mật độ tương đối", ylim=(0, 2.5),
              title=f"v1: cung thưa {longest_circular_run(low_v1)[0] * AZ_BIN_DEG:.0f}° ≥ 20° -> REJECT (SAI). "
                    f"v2: {longest_circular_run(low_v2)[0] * AZ_BIN_DEG:.0f}° -> OK")
    ax[1].legend()
    fig.suptitle("fail_01 — Lớp Metric: mật độ theo azimuth phụ thuộc cảnh (tường gần), không chỉ phụ thuộc sensor",
                 fontsize=13)
    fig.tight_layout()
    fig.savefig(out / "fail_01_rule_v1_wall_shadow_000004.png", dpi=90)
    plt.close(fig)


def fail_02(out: Path, seed: int = 0) -> None:
    root, keep = "data/kitti_mini", 0.3
    frames = list_frames(root)
    clean = [clean_xyz(load_points(root, f)) for f in frames]
    dirty = [sector_attenuation(np.c_[c, np.zeros(len(c))], keep, seed + zlib.crc32(f.encode()) % 10_000)[:, :3]
             for c, f in zip(clean, frames)]
    h_clean = np.array([azimuth_profile(c) for c in clean])
    h_dirty = np.array([azimuth_profile(d) for d in dirty])
    i = frames.index("000011")
    ratio_self = h_dirty[i] / np.maximum(np.median(h_dirty, axis=0), 1)
    ratio_clean = h_dirty[i] / np.maximum(np.median(h_clean, axis=0), 1)
    n_self = sum(longest_circular_run(h < LOW_BIN_FRAC * np.maximum(np.median(h_dirty, 0), 1))[0] * AZ_BIN_DEG >= 20
                 for h in h_dirty)
    n_clean = sum(longest_circular_run(h < LOW_BIN_FRAC * np.maximum(np.median(h_clean, 0), 1))[0] * AZ_BIN_DEG >= 20
                  for h in h_dirty)

    fig, ax = plt.subplots(1, 2, figsize=(16, 6))
    bev(ax[0], dirty[i], f"kitti 000011 sau khi che {1 - keep:.0%} điểm trong cung 30°–70° (mọi frame)",
        [(30, 70, "orange", "vùng bị che (giả lập bùn bám)")])
    ax[1].plot(AZ_CENTERS, ratio_self, color="orange", label="self-baseline (trung vị log bẩn)")
    ax[1].plot(AZ_CENTERS, ratio_clean, "b-", label="clean-baseline (trung vị log sạch)")
    ax[1].axhline(LOW_BIN_FRAC, c="k", ls="--", lw=0.8)
    ax[1].axvspan(30, 70, color="orange", alpha=0.12)
    ax[1].set(xlabel="azimuth (deg)", ylabel="mật độ tương đối", ylim=(0, 3),
              title=f"Frame bị gắn cờ: self-baseline {n_self}/{len(frames)}, clean-baseline {n_clean}/{len(frames)}")
    ax[1].legend()
    fig.suptitle("fail_02 — Lớp Metric: lỗi kéo dài trên mọi frame trở thành 'bình thường' nếu baseline lấy từ chính log",
                 fontsize=13)
    fig.tight_layout()
    fig.savefig(out / "fail_02_self_baseline_blind_persistent_dirt.png", dpi=90)
    plt.close(fig)
    print(f"fail_02: self-baseline flagged {n_self}/{len(frames)}, clean-baseline flagged {n_clean}/{len(frames)}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Vẽ ảnh failure case cho rule SECTOR_GAP")
    ap.add_argument("--out-dir", default="results/figures")
    args = ap.parse_args()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    fail_01(out)
    fail_02(out)
    print(f"-> {out}/fail_01_*.png, {out}/fail_02_*.png")


if __name__ == "__main__":
    main()
