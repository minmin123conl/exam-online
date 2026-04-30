# Test report — PR #2 (Render embedded tables in MC questions)

**Tested branch:** `devin/1777542028-tables` on https://github.com/minmin123conl/exam-online/pull/2
**Frontend:** https://dist-ophczzau.devinapps.com
**Backend:** https://backend-test--am.fly.dev
**Exam under test:** Đề thi Sinh học 11 - Cuối kỳ 2 (id=5, 120 câu, re-imported sau khi parser hỗ trợ bảng)
**Test code minted:** `37RDDU5G`
**Devin session:** https://app.devin.ai/sessions/a17e2d7563884cb29d78f1c41369ae22

## Summary

Một flow end-to-end (admin preview + student exam) cho Câu 4 đề Sinh 11. **Cả hai assertion chính đều pass** — bảng ghép cột hiển thị đúng dạng `<table>` với nội dung tiếng Việt khớp file gốc, không có chuỗi `[TABLE:base64...]` literal lọt lên UI.

## Test cases

### TC1: Admin question editor renders matching table at Câu 4 — PASSED

Steps: Login admin → mở exam id=5 → tab "Câu hỏi" → search "Ghép nội dung" → cuộn tới Câu 4.

Evidence:

![Admin Câu 4 hiển thị bảng 2 cột](https://app.devin.ai/attachments/bebd647c-92a9-460d-a509-7bb793c6bd1c/screenshot_dfbaa784b18f426e9956ef4539a151f3.png)

Assertions:
- Render thành `<table><tbody><tr><td>...` thực sự (xác nhận trong DOM strip)
- Cell (1,1) = `1. Sinh trưởng sơ cấp` ✓
- Cell (1,2) = `a. Là sự sinh trưởng của thân và rễ theo chiều dài do hoạt động của mô phân sinh đỉnh.` ✓
- Cell (3,1) = `2. Sinh trưởng thứ cấp` ✓
- Cell (3,2) = `c. Là sự tăng trưởng bề ngang của cây do mô phân sinh bên của cây thân gỗ hoạt động tạo ra.` ✓
- Hàng 2 và 4 chỉ có 1 cell phải (`b. Diễn ra ở thực vật 2 lá mầm.` / `d. Diễn ra ở thực vật 1 lá mầm.`) — bố cục giữ nguyên file gốc
- 4 phương án A/B/C/D vẫn dưới bảng, đáp án đúng D (`1-ad, 2-bc.`) hightlight xanh
- Không có chuỗi `[TABLE:`/base64 nào hiện lên trên UI

Câu 5/6/17 (cùng cơ chế bảng) cũng được spot-check trong cùng DOM dump — tất cả render thành `<table>` đúng.

### TC2: Student exam view renders matching table at Câu 4 — PASSED

Steps: Trang vào thi → nhập mã `37RDDU5G` + tên `Test Bảng` → click ô số 4 trong "Danh sách câu" → câu hỏi Câu 4.

Evidence:

![Student Câu 4 - bảng + 4 phương án](https://app.devin.ai/attachments/40b8c192-cdf4-4675-be86-89c331323649/screenshot_eb486e890b964643ae5c516b8b4814fe.png)

![Student Câu 4 - chọn đáp án D, counter cập nhật](https://app.devin.ai/attachments/80cc70a6-e0e0-4761-802c-383b65f83bb3/screenshot_2153287228124c93a49ebc40a07d3e1a.png)

Assertions:
- Render thành `<table>` y hệt admin
- 4 phương án A/B/C/D click được, click D → radio highlight xanh
- Counter `1/120 đã chọn` cập nhật → state lưu được
- Không có chuỗi `[TABLE:base64...]` literal

## Out of scope (chưa test)

- Chấm điểm + xem lại bài làm sau khi nộp — không nộp bài để giữ mã `37RDDU5G` cho user dùng nếu muốn xem trực tiếp
- Câu Đúng/Sai (91-102) chấm điểm — không thay đổi trong PR này, nhưng nguy cơ regression nhẹ nếu logic phân loại bảng đáp án TF vs content table sai. Spot-check trong DOM dump cho thấy Câu 91-102 vẫn có 4 ý a/b/c/d với marker Đúng/Sai → bảng đáp án TF được nhận diện đúng (không leo vào content)
- Câu có ảnh trong cell — Sinh 11 không có

## Recording

File video kèm theo (`.mp4`) thể hiện toàn bộ flow trên.
