# Báo cáo Day 6: Data health dashboard cho LiDAR

> Thay **mọi** ô có chữ ĐIỀN nằm trong ngoặc vuông bằng nội dung của bạn, xoá luôn cả dấu ngoặc vuông. Lệnh `python tools/check_submission.py` sẽ báo FAIL nếu còn sót bất kỳ chỗ nào.

- **Họ tên:** Nguyễn Nhật Thăng
- **MSSV:** 2A202602727 (phải trùng với MSSV trong tên repo `<HoVaTen>-<MSSV>-Track4-Day21`)
- **Lớp:** Track 4
- **Link repo:** (https://github.com/nhat-thang/NguyenNhatThang-2A202602727-Track4-Day21)
- **Topic:** E — Data health dashboard
- **Dataset:** data/synthetic, data/kitti_mini, data/nuscenes_mini_subset
- **Các frame đã dùng:** toàn bộ: synthetic 000000–000004 (5 frame), kitti_mini 20 frame (000001 … 000061), nuScenes scene-0103_000 … scene-0103_039 (ngày) và scene-1094_000 … scene-1094_039 (đêm)

> Hãy viết ngắn: mỗi mục từ 3 đến 8 dòng, ưu tiên số liệu và hình ảnh.

## 1. Claim

Một câu khẳng định kỹ thuật có thể kiểm chứng. Ví dụ: *"Lệch yaw 1° làm 12% điểm LiDAR rơi ra khỏi vật thể ở 30 m, phát hiện được bằng edge-alignment score với ngưỡng X."*

*(Nháp CP1)* Bộ rule cảnh báo dựa trên 3 metric không cần model (invalid ratio > 0, độ phủ azimuth < 90 %, time gap > 1.5 × chu kỳ trung vị) phát hiện được 100 % lỗi cài sẵn trong `data/synthetic` và gắn cờ REJECT cho ≤ 10 % frame của `kitti_mini` và `nuscenes_mini_subset`.

## 2. Evidence

Bảng hoặc plot số liệu, kèm ảnh/video demo. Ghi rõ đường dẫn file trong `results/`.

| Cấu hình / mức perturb | Metric 1 | Metric 2 | Ghi chú |
|---|---|---|---|
| [ĐIỀN] | | | |

![demo](../results/figures/[ĐIỀN].png)

## 3. Failure case

Nêu khi nào hệ thống hoặc phương pháp fail, vì sao fail, và liên hệ tới lớp nào trong 6 lớp debug: I/O, Geometry, Time, Preprocess, Model, Metric.

![failure](../results/figures/fail_01_rule_v1_wall_shadow_000004.png)

**fail_01: báo nhầm "sensor bị che" (lớp Metric).** Rule v1 so mỗi bin azimuth 5° với trung vị các bin của *chính frame* đó. Ở synthetic `000004`, rule v1 thấy cung +40°…+65° chỉ còn 0.43–0.49 lần trung vị, kéo dài 25° (vượt ngưỡng 20°), nên gắn REJECT. Thực ra sensor không hỏng: bức tường bên trái (y ≈ 9 m) chắn mọi tia, nên cung này chỉ còn điểm ở gần hơn 15 m. Khi xe tiến lên, cung bị tường chắn rộng dần (15° ở `000000`, 25° ở `000004`). Nguyên nhân gốc: mật độ theo azimuth phụ thuộc **cảnh** chứ không chỉ phụ thuộc sensor, vì vậy so với chính frame thì không phân biệt được hai trường hợp. **Cách sửa (rule v2):** so mỗi bin với trung vị của *cùng bin đó* trên nhiều frame. Bóng che cố định khi đó cũng thấp trong profile tham chiếu, nên v2 cho `000004` OK mà vẫn bắt được cung 35° bị che ở `000003`.

![failure2](../results/figures/fail_02_self_baseline_blind_persistent_dirt.png)

**fail_02: không phát hiện lỗi kéo dài (lớp Metric).** Cho rule v2 lấy profile tham chiếu từ *chính log đang kiểm tra* (self-baseline), rồi che 70% điểm trong cung 30°–70° ở **mọi** frame KITTI (giả lập bùn bám suốt cả chuyến). Kết quả: tham chiếu bị che theo, nên **0/20** frame bị gắn cờ. Nếu dùng baseline lấy từ log sạch của cùng sensor thì **20/20** frame bị gắn cờ. Sweep ở mục 2 cho thấy cùng hiện tượng với random dropout và range dropout (self-baseline phát hiện 0–5%). **Cách phát hiện khi chạy thật:** lưu một baseline profile cho mỗi xe/sensor ngay sau khi calibration, so mọi log với baseline đó, và cảnh báo khi baseline cũ hơn N ngày.

## 4. Khuyến nghị nếu triển khai thật

Use-case cụ thể (ADAS / robot / drone), trade-off và bước tiếp theo.

[ĐIỀN]

## 5. Cách chạy lại

Các lệnh tái tạo lại toàn bộ kết quả từ repo sạch.

```bash
python -m starter.projection --data-root data/synthetic --frame 000000      # test CP2
python -m src.dashboard --data-root data/synthetic --name synthetic
python -m src.dashboard --data-root data/kitti_mini --name kitti
python -m src.dashboard --data-root data/nuscenes_mini_subset --name nusc
python -m src.degradation_sweep       # khoảng 2 phút
python -m src.latency
python -m src.failure_cases
```

## 6. Khai báo sử dụng AI

Ghi rõ đã dùng công cụ AI nào, dùng vào việc gì, và bạn đã tự kiểm chứng kết quả đó bằng cách nào. Nếu không dùng AI, ghi "Không sử dụng". Xem quy định ở `RULES.md` mục 2.

| Công cụ | Dùng cho việc gì | Bạn đã kiểm chứng thế nào |
|---|---|---|
| [ĐIỀN] | | |
