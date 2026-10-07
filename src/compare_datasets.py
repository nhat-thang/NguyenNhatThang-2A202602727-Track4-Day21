"""Advanced topic E: so sánh KITTI (64 beam) vs nuScenes (32 beam), ngày vs đêm, và xếp hạng frame nên gán nhãn.
Đọc CSV do `src.dashboard` sinh ra, nên chạy dashboard cho 3 dataset trước.

    python -m src.compare_datasets

Kết quả:
    results/dataset_comparison.csv      trung vị metric theo nhóm (KITTI / nuScenes ngày / nuScenes đêm)
    results/frame_ranking.csv           mọi frame, xếp hạng frame_score TRONG từng dataset
    results/figures/compare_datasets.png
    results/figures/frame_ranking.png   top frame + ảnh frame được ưu tiên + frame bị REJECT
"""
from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Wedge

from starter.datasets import load_frame, load_points
from starter.projection import draw_box2d, overlay_points, project_velo_to_image

GROUPS = {"kitti": "KITTI (64 beam, ngày)", "nusc_day": "nuScenes ngày (32 beam, scene-0103)",
          "nusc_night": "nuScenes đêm sau mưa (scene-1094)"}
ROOTS = {"kitti": "data/kitti_mini", "nusc": "data/nuscenes_mini_subset", "synthetic": "data/synthetic"}
METRICS = ["n_points", "n_returns", "near_ratio", "range_p50", "range_p95", "intensity_mean", "intensity_p95", "fov_ratio", "img_brightness",
           "az_density_cv", "n_objects", "n_vru", "n_sparse_objects", "median_pts_per_object", "sync_offset_ms"]


def load(results: Path) -> pd.DataFrame:
    k = pd.read_csv(results / "health_kitti.csv", dtype={"frame_id": str}).assign(dataset="kitti", group="kitti")
    n = pd.read_csv(results / "health_nusc.csv", dtype={"frame_id": str}).assign(dataset="nusc")
    n["group"] = np.where(n["frame_id"].str.startswith("scene-0103"), "nusc_day", "nusc_night")
    s = pd.read_csv(results / "health_synthetic.csv", dtype={"frame_id": str}).assign(dataset="synthetic",
                                                                                    group="synthetic")
    return pd.concat([k, n, s], ignore_index=True)


def overlay(dataset: str, fid: str) -> np.ndarray:
    fr = load_frame(ROOTS[dataset], fid)
    uv, depth, _ = project_velo_to_image(fr["points"], fr["calib"], fr["image"].shape)
    vis = overlay_points(fr["image"], uv, depth, radius=2 if fr["image"].shape[1] > 1300 else 1)
    for o in fr["labels"]:
        vis = draw_box2d(vis, o.bbox, label=o.type)
    return cv2.cvtColor(vis, cv2.COLOR_BGR2RGB)


def plot_compare(df: pd.DataFrame, out: Path) -> None:
    real = df[df["group"].isin(GROUPS)]
    show = [("n_returns", "Return thật / frame (r ≥ 1 m)"), ("median_pts_per_object", "Trung vị điểm LiDAR / object"),
            ("intensity_mean", "Intensity TB (0–1)"), ("img_brightness", "Độ sáng ảnh camera (0–255)"),
            ("range_p95", "Range p95 (m)"), ("fov_ratio", "% điểm trong FOV camera")]
    fig, axes = plt.subplots(2, 3, figsize=(16, 8))
    for ax, (col, title) in zip(axes.ravel(), show):
        data = [real.loc[real["group"] == g, col].dropna() for g in GROUPS]
        ax.boxplot(data, tick_labels=["KITTI", "nuSc ngày", "nuSc đêm"], showfliers=True)
        ax.set_title(title)
        ax.grid(alpha=0.3)
    axes[0, 1].set_yscale("log")
    fig.suptitle("KITTI 64 beam vs nuScenes 32 beam, ngày vs đêm (mỗi điểm dữ liệu = 1 frame)", fontsize=13)
    fig.tight_layout()
    fig.savefig(out, dpi=90)
    plt.close(fig)


def plot_ranking(rank: pd.DataFrame, out: Path) -> None:
    fig = plt.figure(figsize=(18, 11))
    gs = fig.add_gridspec(3, 2, height_ratios=[1.1, 1, 1])
    ax = fig.add_subplot(gs[0, 0])
    top = rank[rank["dataset"] != "synthetic"].groupby("dataset").head(6)
    colors = top["dataset"].map({"kitti": "#1f6fb4", "nusc": "#d0602a"})
    ax.barh(range(len(top))[::-1], top["frame_score"], color=colors)
    ax.set_yticks(range(len(top))[::-1], [f"{r.frame_id} (#{r.rank_in_dataset}, VRU={r.n_vru}, "
                                         f"thưa={r.n_sparse_objects})" for r in top.itertuples()], fontsize=8)
    ax.set(title="Top 6 frame nên gán nhãn trong mỗi dataset (xanh = KITTI, cam = nuScenes)", xlabel="frame_score")

    ax = fig.add_subplot(gs[0, 1])
    pts = load_points(ROOTS["synthetic"], "000003")
    pts = pts[np.isfinite(pts).all(1)]
    r = rank[(rank["dataset"] == "synthetic") & (rank["frame_id"] == "000003")].iloc[0]
    ax.scatter(pts[:, 0], pts[:, 1], s=0.3, c="k")
    c, w = r["az_gap_center_deg"], r["max_az_gap_deg"]
    ax.add_patch(Wedge((0, 0), 60, c - w / 2, c + w / 2, color="red", alpha=0.25))
    ax.set(xlim=(-20, 45), ylim=(-30, 30), aspect="equal",
           title=f"Frame bị REJECT: synthetic 000003 (score=0)\n{r['flags']}")
    ax.title.set_fontsize(9)

    for i, ds in enumerate(["kitti", "nusc"]):
        best = rank[rank["dataset"] == ds].iloc[0]
        ax = fig.add_subplot(gs[1 + i, :])
        ax.imshow(overlay(ds, best["frame_id"]))
        ax.set_title(f"#1 {ds}: {best['frame_id']} — {best['n_objects']} object, {best['n_vru']} VRU, "
                     f"{best['n_sparse_objects']} object < 10 điểm LiDAR, score={best['frame_score']}")
        ax.axis("off")
    fig.tight_layout()
    fig.savefig(out, dpi=80)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description="So sánh dataset/ngày-đêm và xếp hạng frame theo frame_score")
    ap.add_argument("--results", default="results", help="thư mục chứa health_*.csv")
    args = ap.parse_args()
    res = Path(args.results)
    df = load(res)

    comp = df[df["group"].isin(GROUPS)].groupby("group")[METRICS].median().reindex(list(GROUPS)).T
    comp.columns = [GROUPS[g] for g in comp.columns]
    comp.round(3).to_csv(res / "dataset_comparison.csv")
    print(comp.round(3).to_string())

    rank = df.sort_values(["dataset", "frame_score"], ascending=[True, False]).copy()
    rank["rank_in_dataset"] = rank.groupby("dataset").cumcount() + 1
    cols = ["dataset", "rank_in_dataset", "frame_id", "frame_score", "status", "flags", "n_objects", "n_vru",
            "n_sparse_objects", "median_pts_per_object", "max_az_gap_deg", "az_gap_center_deg"]
    rank[cols].to_csv(res / "frame_ranking.csv", index=False)
    print(rank[cols[:9]].groupby("dataset").head(3).to_string(index=False))

    (res / "figures").mkdir(parents=True, exist_ok=True)
    plot_compare(df, res / "figures" / "compare_datasets.png")
    plot_ranking(rank[cols], res / "figures" / "frame_ranking.png")
    print(f"-> {res / 'dataset_comparison.csv'}, {res / 'frame_ranking.csv'}, figures/compare_datasets.png, "
          f"figures/frame_ranking.png")


if __name__ == "__main__":
    main()
