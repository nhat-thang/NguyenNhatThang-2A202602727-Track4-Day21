"""Đo latency tính metric health cho 1 frame (không tính đọc đĩa): bỏ lần chạy đầu, lặp >= 20 lần, báo p50/p95.

    python -m src.latency --repeats 30
"""
from __future__ import annotations

import argparse
import platform
import time
from pathlib import Path

import numpy as np
import pandas as pd

from starter.datasets import list_frames, load_frame
from src.health import frame_metrics


def main() -> None:
    ap = argparse.ArgumentParser(description="Latency p50/p95 của frame_metrics trên mỗi dataset")
    ap.add_argument("--datasets", nargs="+", default=["data/kitti_mini", "data/nuscenes_mini_subset"])
    ap.add_argument("--frames-per-dataset", type=int, default=5)
    ap.add_argument("--repeats", type=int, default=30)
    ap.add_argument("--out", default="results/latency.csv")
    args = ap.parse_args()

    rows = []
    for root in args.datasets:
        frames = list_frames(root)[: args.frames_per_dataset]
        loaded = [load_frame(root, f) for f in frames]
        frame_metrics(loaded[0])                                  # warm-up, bỏ
        times = []
        for _ in range(args.repeats):
            for fr in loaded:
                t0 = time.perf_counter()
                frame_metrics(fr)
                times.append((time.perf_counter() - t0) * 1e3)
        t = np.array(times)
        rows.append({"dataset": Path(root).name, "n_points_median": int(np.median([len(f["points"]) for f in loaded])),
                     "n_samples": len(t), "p50_ms": round(np.percentile(t, 50), 2),
                     "p95_ms": round(np.percentile(t, 95), 2), "cpu": platform.processor() or platform.machine()})
    df = pd.DataFrame(rows)
    df.to_csv(args.out, index=False)
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
