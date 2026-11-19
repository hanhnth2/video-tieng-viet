---
title: Video chuyen doi Tieng Viet
emoji: 🎬
colorFrom: red
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
short_description: Video Xiaohongshu sang video tiếng Việt – Ngô Thị Hồng Hạnh
---

# Video chuyển đổi Tiếng Việt

Phần mềm được tạo bởi **Ngô Thị Hồng Hạnh**: lồng tiếng Việt, dịch chữ trên hình, xoá logo Xiaohongshu.

## Cài đặt Space (làm 1 lần)
1. Tạo tài khoản miễn phí tại https://huggingface.co (đăng ký bằng email).
2. Bấm **New → Space**: đặt tên `video-tieng-viet`, chọn **Docker → Blank**, phần cứng **CPU basic (Free)**,
   chế độ **Public** (đã có mật khẩu bảo vệ bên trong) → **Create Space**.
3. Vào tab **Files → Add file → Upload files**, chọn 3 file: `Dockerfile`, `README.md`, `xhs2vi.zip` → **Commit**.
4. Vào **Settings → Variables and secrets**:
   - **New secret** `APP_PASSWORD` = mật khẩu của bạn (bắt buộc, để người lạ không dùng được).
   - (tuỳ chọn) secret `XHS_COOKIE` = cookie Xiaohongshu; secret `ANTHROPIC_API_KEY` = khoá Claude để dịch hay hơn.
   - (tuỳ chọn) variable `WHISPER_MODEL` = `small` (mặc định, nhanh) hoặc `medium` (chính xác hơn, chậm hơn).
5. Chờ 10–20 phút để Space build xong (trạng thái **Running**).
6. Link web cố định: `https://<tên-tài-khoản>-video-tieng-viet.hf.space` → dán vào ứng dụng Android, nhập mật khẩu.

## Lưu ý
- Gói miễn phí chỉ có CPU: video 1 phút mất khoảng 5–15 phút để xử lý.
- Không ai dùng trong 48 giờ, Space tạm ngủ; lần mở sau chờ 1–2 phút để thức dậy.
- Lịch sử video có thể mất khi Space khởi động lại → tải video về máy ngay sau khi xong.
- Cập nhật phần mềm: tải `xhs2vi.zip` mới lên đè file cũ, Space tự build lại.
