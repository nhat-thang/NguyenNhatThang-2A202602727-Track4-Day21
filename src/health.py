"""Data health cho LiDAR (topic E): metric từng frame, rule cảnh báo, frame score.

Không cần model. Mọi metric chỉ dùng point cloud, calib, label và timestamp.
Mở rộng `starter.data_health.point_stats` với:
  - mật độ theo azimuth (độ phủ, cung trống dài nhất) và theo elevation
  - % điểm rơi vào FOV camera (dùng velo_to_cam / cam_to_image của CP2)
  - số điểm LiDAR trong từng 3D box GT (object "khó gán nhãn" nếu < MIN_PTS_PER_OBJ)
  - time gap giữa hai frame liên tiếp, độ lệch LiDAR-camera (nuScenes)
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pandas as pd

from starter.data_health import point_stats
from starter.datasets import dataset_type, list_frames, load_frame
from starter.projection import project_velo_to_image, velo_to_cam

AZ_BIN_DEG = 5.0                 # 72 bin azimuth
ELEV_BIN_DEG = 0.25              # đủ mịn để thấy từng beam của HDL-64 (~0.4°) và HDL-32 (~1.33°)
RANGE_BINS = np.arange(0, 102, 2.0)
INTENSITY_BINS = np.linspace(0, 1, 51)
LOW_BIN_FRAC = 0.5               # bin azimuth "thưa bất thường" nếu < 50% trung vị số điểm/bin của frame
MIN_PTS_PER_OBJ = 10             # object có < 10 điểm LiDAR thì khó gán nhãn 3D
VRU_TYPES = {"Pedestrian", "Cyclist", "Bicycle", "Motorcycle", "Person_sitting"}

# ---- Ngưỡng của rule (giải thích trong REPORT mục 2) ----
TH_INVALID_REJECT = 0.01         # > 1% điểm NaN/Inf -> lỗi driver/I/O nghiêm trọng
TH_AZ_GAP_DEG = 20.0             # cung trống liên tục >= 20° -> sensor bị che / mất packet
TH_TIME_GAP_RATIO = 1.5          # dt > 1.5 x chu kỳ trung vị -> rớt frame
TH_SYNC_MS = 50.0                # |t_cam - t_lidar| > 50 ms -> lệch đồng bộ
TH_POINTS_DROP = 0.85            # n_points < 85% trung vị dataset -> mất điểm
TH_RANGE_DROP = 0.6              # range_p95 < 60% trung vị dataset -> tầm nhìn ngắn (sương/bẩn)


def azimuth_profile(xyz: np.ndarray) -> np.ndarray:
    az = np.degrees(np.arctan2(xyz[:, 1], xyz[:, 0]))
    hist, _ = np.histogram(az, bins=int(360 / AZ_BIN_DEG), range=(-180, 180))
    return hist


def elevation_profile(xyz: np.ndarray) -> np.ndarray:
    el = np.degrees(np.arctan2(xyz[:, 2], np.linalg.norm(xyz[:, :2], axis=1)))
    hist, _ = np.histogram(el, bins=int(45 / ELEV_BIN_DEG), range=(-35, 10))
    return hist


def longest_circular_run(mask: np.ndarray) -> tuple[int, int]:
    """(độ dài, chỉ số bin bắt đầu) của chuỗi True liên tiếp dài nhất trên vòng tròn (bin cuối nối bin đầu)."""
    if mask.all():
        return len(mask), 0
    offset = int(np.argmin(mask))                 # xoay để bắt đầu bằng một bin False
    m = np.roll(mask, -offset)
    best, best_start, run = 0, 0, 0
    for i, v in enumerate(m):
        run = run + 1 if v else 0
        if run > best:
            best, best_start = run, i - run + 1
    return best, (best_start + offset) % len(mask)


def points_in_box(pts_cam: np.ndarray, obj) -> int:
    """Đếm điểm (camera frame) nằm trong 3D box KITTI (location = tâm đáy, y hướng xuống)."""
    h, w, l = obj.dimensions
    c, s = np.cos(obj.rotation_y), np.sin(obj.rotation_y)
    R = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])       # object -> camera
    local = (pts_cam - obj.location) @ R                   # = R.T @ (p - loc), từng hàng
    return int(((np.abs(local[:, 0]) <= l / 2) & (local[:, 1] <= 0) & (local[:, 1] >= -h)
                & (np.abs(local[:, 2]) <= w / 2)).sum())


def load_timestamps(data_root: str | Path, frames: list[str], frs: dict) -> np.ndarray:
    """Timestamp (giây) của từng frame. KITTI 3D Object không có -> NaN."""
    if dataset_type(data_root) == "nuscenes":
        return np.array([frs[f]["timestamp_lidar_us"] * 1e-6 for f in frames])
    ts_file = Path(data_root) / "training" / "timestamps.txt"
    if ts_file.exists():
        ts = np.loadtxt(ts_file, ndmin=1)
        if len(ts) == len(frames):
            return ts
    return np.full(len(frames), np.nan)


def frame_metrics(fr: dict) -> tuple[dict, dict[str, np.ndarray]]:
    pts = fr["points"]
    row = point_stats(pts, n_azimuth_bins=int(360 / AZ_BIN_DEG))
    valid = pts[np.isfinite(pts).all(axis=1)]
    xyz = valid[:, :3]

    az_hist = azimuth_profile(xyz)
    low = az_hist < LOW_BIN_FRAC * np.median(az_hist)
    el_hist = elevation_profile(xyz)
    rng_hist, _ = np.histogram(np.linalg.norm(xyz[:, :2], axis=1), bins=RANGE_BINS)
    int_hist, _ = np.histogram(valid[:, 3], bins=INTENSITY_BINS)

    _, _, in_fov = project_velo_to_image(valid, fr["calib"], fr["image"].shape)
    pts_cam = velo_to_cam(xyz, fr["calib"])
    obj_pts = [points_in_box(pts_cam, o) for o in fr["labels"]]
    sparse = [n < MIN_PTS_PER_OBJ for n in obj_pts]

    row.update({
        "intensity_p95": float(np.percentile(valid[:, 3], 95)) if len(valid) else np.nan,
        "az_coverage": float(1 - low.mean()),
        "max_az_gap_self_deg": float(longest_circular_run(low)[0] * AZ_BIN_DEG),   # rule v1 (xem failure case)
        "az_density_cv": float(az_hist.std() / max(az_hist.mean(), 1e-9)),
        "elev_rows": int((el_hist > 0.002 * el_hist.sum()).sum()),   # số bin elevation 0.25° chứa > 0.2% điểm
        "fov_ratio": float(in_fov.mean()) if len(in_fov) else np.nan,
        "img_brightness": float(cv2.cvtColor(fr["image"], cv2.COLOR_BGR2GRAY).mean()),
        "n_objects": len(fr["labels"]),
        "n_vru": sum(o.type in VRU_TYPES for o in fr["labels"]),
        "n_sparse_objects": int(sum(sparse)),
        "median_pts_per_object": float(np.median(obj_pts)) if obj_pts else np.nan,
        "sync_offset_ms": (abs(fr["timestamp_camera_us"] - fr["timestamp_lidar_us"]) / 1e3
                           if "timestamp_lidar_us" in fr else np.nan),
    })
    return row, {"azimuth": az_hist, "elevation": el_hist, "range": rng_hist, "intensity": int_hist}


def make_baseline(df: pd.DataFrame, hists: dict[str, np.ndarray]) -> dict:
    """Baseline của sensor (lấy từ một log sạch): giá trị 'bình thường' mà các rule tương đối so vào."""
    return {"az_ref": np.median(hists["azimuth"], axis=0), "n_points": float(df["n_points"].median()),
            "range_p95": float(df["range_p95"].median()), "time_gap_s": float(df["time_gap_s"].median())}


def reference_gaps(az_hists: np.ndarray, az_ref: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Rule v2: so mỗi bin azimuth với trung vị CÙNG bin đó trên toàn dataset (profile tham chiếu),
    thay vì với trung vị các bin của chính frame (rule v1). Bóng che cố định (tường, thân xe ego) có mặt
    ở mọi frame nên profile tham chiếu cũng thấp -> không bị tính là gap; mất điểm đột ngột thì bị tính.
    Trả về (cung thưa liên tục dài nhất (deg), azimuth tâm cung đó (deg)) cho từng frame."""
    ref = np.maximum(az_ref, 1)
    gaps, centers = [], []
    for h in az_hists:
        n, start = longest_circular_run(h < LOW_BIN_FRAC * ref)
        gaps.append(n * AZ_BIN_DEG)
        centers.append(-180 + (start + n / 2) * AZ_BIN_DEG if n else np.nan)
    return np.array(gaps), (np.array(centers) + 180) % 360 - 180


def apply_rules(df: pd.DataFrame, baseline: dict) -> pd.DataFrame:
    """Thêm cột flags (lý do), status OK/REVIEW/REJECT. Ngưỡng tương đối so với `baseline`."""
    med_n, med_rng, med_dt = baseline["n_points"], baseline["range_p95"], baseline["time_gap_s"]
    flags_col, status_col = [], []
    for _, r in df.iterrows():
        reject, warn = [], []
        if r["invalid_ratio"] > TH_INVALID_REJECT:
            reject.append(f"INVALID {r['invalid_ratio']:.1%} > {TH_INVALID_REJECT:.0%}")
        elif r["invalid_ratio"] > 0:
            warn.append(f"NAN_POINTS {r['invalid_ratio']:.2%}")
        if r["max_az_gap_deg"] >= TH_AZ_GAP_DEG:
            reject.append(f"SECTOR_GAP {r['max_az_gap_deg']:.0f}deg@{r['az_gap_center_deg']:.0f}")
        if np.isfinite(r["time_gap_s"]) and r["time_gap_s"] > TH_TIME_GAP_RATIO * med_dt:
            warn.append(f"TIME_GAP {r['time_gap_s']:.3f}s > {TH_TIME_GAP_RATIO}x{med_dt:.3f}s")
        if np.isfinite(r["sync_offset_ms"]) and r["sync_offset_ms"] > TH_SYNC_MS:
            warn.append(f"SYNC {r['sync_offset_ms']:.0f}ms")
        if r["n_points"] < TH_POINTS_DROP * med_n:
            warn.append(f"POINT_DROP {r['n_points'] / med_n:.0%} of median")
        if r["range_p95"] < TH_RANGE_DROP * med_rng:
            warn.append(f"SHORT_RANGE p95={r['range_p95']:.1f}m")
        flags_col.append("; ".join(reject + warn))
        status_col.append("REJECT" if reject else "REVIEW" if warn else "OK")
    out = df.copy()
    out["flags"] = flags_col
    out["status"] = status_col
    return out


def frame_score(df: pd.DataFrame) -> pd.Series:
    """Điểm ưu tiên gán nhãn: frame càng nhiều object khó (VRU, object thưa điểm) càng nên gán nhãn,
    nhưng frame lỗi sensor thì không đáng tốn công: REJECT -> 0, REVIEW -> x0.5."""
    value = df["n_objects"] + 2.0 * df["n_vru"] + 1.5 * df["n_sparse_objects"]
    health = df["status"].map({"OK": 1.0, "REVIEW": 0.5, "REJECT": 0.0})
    return (value * health).round(2)


def analyze(data_root: str | Path, points_fn=None, baseline: dict | None = None, cache: dict | None = None
            ) -> tuple[pd.DataFrame, dict[str, np.ndarray]]:
    """Chạy toàn bộ dataset. `points_fn(points, frame_id) -> points` để chèn degradation (thí nghiệm sweep).
    `baseline=None`: tự lấy trung vị của chính log này làm baseline (self-baseline, dùng khi chưa có log sạch).
    Truyền baseline từ log sạch (`make_baseline`) để phát hiện cả lỗi kéo dài trên mọi frame.
    `cache`: dict frame_id -> frame đã đọc, để chạy nhiều cấu hình mà không đọc lại đĩa.
    Trả về (bảng metric + flags + score, dict histogram mỗi loại có shape (F, n_bins))."""
    frames = list_frames(data_root)
    frs, rows = {}, []
    hists: dict[str, list] = {}
    for fid in frames:
        if cache is not None and fid in cache:
            fr = cache[fid]
        else:
            fr = load_frame(data_root, fid)
            if cache is not None:
                cache[fid] = fr
        if points_fn is not None:
            fr = {**fr, "points": points_fn(fr["points"], fid)}
        frs[fid] = {k: v for k, v in fr.items() if k.startswith("timestamp")}
        row, h = frame_metrics(fr)
        rows.append({"frame_id": fid, **row})
        for k, v in h.items():
            hists.setdefault(k, []).append(v)
    hists = {k: np.array(v) for k, v in hists.items()}
    df = pd.DataFrame(rows)
    ts = load_timestamps(data_root, frames, frs)
    df["timestamp_s"] = ts
    gaps = np.diff(ts, prepend=np.nan)
    if dataset_type(data_root) == "nuscenes":         # khoảng cách giữa 2 scene không phải lỗi rớt frame
        scene = df["frame_id"].str.rsplit("_", n=1).str[0]
        gaps[(scene != scene.shift()).to_numpy()] = np.nan
    df["time_gap_s"] = gaps
    if baseline is None:
        baseline = make_baseline(df, hists)
    df["max_az_gap_deg"], df["az_gap_center_deg"] = reference_gaps(hists["azimuth"], baseline["az_ref"])
    df = apply_rules(df, baseline)
    df["frame_score"] = frame_score(df)
    return df, hists
