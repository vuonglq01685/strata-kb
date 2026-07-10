---
name: kb-summarize
description: Điền summary L0/L1/L2 cho các section đang pending trong .kb/ sau khi chạy kb ingest. Dùng khi user yêu cầu summarize KB, điền summary, hoặc sau khi vừa ingest tài liệu mới.
---

# KB Summarize — điền tri thức vào khung .kb/

Bạn là "nửa LLM" của pipeline AERO-KB. `kb ingest` đã sinh khung; nhiệm vụ
của bạn là điền phần summary. KHÔNG sửa bất kỳ thứ gì ngoài các vị trí nêu dưới.

## Quy trình

1. Chạy `kb status` — lấy danh sách section pending (doc, section id, file).
2. Với TỪNG section pending, lặp:
   a. Đọc nguyên văn: `kb get <doc-id> <section-id> --level l3`
   b. Mở file L2 (`.kb/<doc-id>/<file>.md`), tìm marker
      `<!-- TODO:summarize <section-id> -->` trong section tương ứng.
   c. Thay marker bằng đoạn văn cô đọng (xem Quy tắc viết). KHÔNG đụng vào
      các bảng markdown đã có sẵn trong section — chúng do code chép nguyên văn.
   d. Mở `.kb/<doc-id>/_manifest.yaml`, điền `summary` (1 câu, ≤ 25 từ)
      cho section đó và đổi `status: pending` → `status: summarized`.
3. Khi mọi section của một doc xong: mở `.kb/index.yaml`, điền/sửa `summary`
   (1 câu) và kiểm tra `title`, `revision`, `tags` của doc đó cho đúng.
4. Chạy `kb build` — phải PASS. Nếu fail vì table integrity: bạn đã lỡ sửa
   bảng, khôi phục bảng về nguyên văn từ file `.raw.md`.
5. Báo cáo: số section đã điền, tổng token L2 (xem `kb stats`).

## Quy tắc viết (bắt buộc)

- Viết **tiếng Anh**.
- Đoạn L2: cô đọng văn xuôi còn ~20–30% độ dài gốc, giữ cấu trúc logic.
- Giữ NGUYÊN VĂN: mọi mã hiệu (P, R, D...), tên record/field (UR, PA...),
  giá trị số, đơn vị, tham chiếu chéo (§x.y). Không diễn đạt lại thuật ngữ.
- KHÔNG suy diễn ngoài văn bản gốc. Thiếu chắc chắn → giữ nguyên câu gốc.
- KHÔNG tóm tắt bảng, không tạo bảng mới, không xóa bảng.
- Summary L1 (manifest): 1 câu ≤ 25 từ, nêu section nói về cái gì và chứa
  loại dữ liệu gì (để BM25 khớp được từ khóa kỹ thuật).

## Làm việc theo lô

Điền lần lượt từng section, mỗi 5–10 section chạy lại `kb build
--allow-pending` để bắt lỗi sớm. Không sửa nhiều file song song.
