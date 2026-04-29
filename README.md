# Exam Online — Nền tảng thi trắc nghiệm

Ứng dụng web cho phép giáo viên đưa đề thi trắc nghiệm lên mạng, cấp mã cho học sinh, học sinh làm đề và xem điểm ngay, có bảng xếp hạng cập nhật trực tiếp.

## Tính năng

### Admin
- Đăng nhập bảo mật (JWT)
- Tạo / sửa / xoá / nhân bản đề thi
- Thêm / sửa / xoá câu hỏi (trắc nghiệm A/B/C/D + câu đúng/sai 4 ý)
- Sinh mã thi hàng loạt hoặc tạo mã tuỳ chỉnh
- Mã thi chỉ dùng được **một lần duy nhất** cho mỗi học sinh
- Xem bảng kết quả chi tiết của từng học sinh, xoá lượt làm, reset mã

### Học sinh
- Nhập mã thi + họ tên → vào làm bài
- Làm trắc nghiệm với timer đếm ngược, điều hướng câu hỏi
- Nộp bài → xem điểm ngay lập tức + bảng trả lời chi tiết (đáp án đúng/sai từng câu)
- Xem bảng xếp hạng cập nhật theo thời gian thực (WebSocket)

### Bảng xếp hạng
- Podium top 3 + danh sách từ cao xuống thấp
- Tự động cập nhật mỗi khi có học sinh nộp bài (WebSocket push)

## Kiến trúc

- **Backend**: FastAPI + SQLAlchemy + SQLite + WebSocket
- **Frontend**: React 19 + TypeScript + Vite + React Router

## Phát triển local

### Backend
```bash
cd backend
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e .
uvicorn app.main:app --reload
```

Mặc định tạo admin `admin / admin123` và seed đề thi mẫu (Lịch sử 12 — 112 MC + 7 TF).
Hãy đổi mật khẩu bằng `EXAM_ADMIN_PASSWORD` khi deploy.

### Frontend
```bash
cd frontend
npm install
npm run dev
```

Đặt `VITE_API_URL` để trỏ sang backend production khi build.

## Biến môi trường backend
- `EXAM_DB_PATH` — đường dẫn file SQLite (mặc định `/tmp/exam.db`)
- `EXAM_SECRET_KEY` — khoá ký JWT
- `EXAM_ADMIN_USER` — username admin mặc định (default `admin`)
- `EXAM_ADMIN_PASSWORD` — mật khẩu admin mặc định (default `admin123`)
