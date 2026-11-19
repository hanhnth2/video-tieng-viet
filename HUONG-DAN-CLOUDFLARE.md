# Link cố định cho phần mềm Video chuyển đổi Tiếng Việt (Cloudflare, miễn phí)

Phần mềm được tạo bởi **Ngô Thị Hồng Hạnh**.

## Vì sao cần?
Máy chủ xử lý video chạy trên Google Colab, mỗi lần chạy có link tạm khác nhau (`…trycloudflare.com`).
Cổng Cloudflare cho bạn **một link cố định** `https://video-tieng-viet.<tài-khoản>.workers.dev`:
Colab tự báo link tạm mới cho cổng, web và ứng dụng Android luôn dùng link cố định.
Khi Colab tắt, link cố định hiện trang "Máy chủ đang tắt" kèm hướng dẫn.

Video vẫn được xử lý trên Colab (Cloudflare Workers không chạy được AI nhận dạng giọng / dựng video).

## Cài đặt (làm 1 lần, chỉ cần trình duyệt)
1. Vào **dash.cloudflare.com** → **Compute (Workers)** (hoặc **Workers & Pages**) → **Create**.
2. Chọn **Import a repository** → chọn repo GitHub **`video-tieng-viet`**.
3. Giữ tên worker là **`video-tieng-viet`**, các thiết lập khác để nguyên → **Deploy**. Chờ 1–2 phút.
4. Vào worker vừa tạo → **Settings → Variables and Secrets → Add**:
   - Type: **Secret**, Name: `REGISTER_TOKEN`, Value: một mã bí mật bạn tự nghĩ (vd `hanh-2026-bimat`) → **Deploy**.
5. Link cố định ở mục **Domains & Routes**, dạng `https://video-tieng-viet.<tài-khoản>.workers.dev`.

## Kết nối Colab với cổng
Trên Colab, bấm biểu tượng 🔑 **Secrets** bên trái, thêm 2 secret (bật *Notebook access*):
- `GATEWAY_URL` = link cố định ở bước 5
- `GATEWAY_TOKEN` = đúng mã `REGISTER_TOKEN` ở bước 4

Từ đó, mỗi lần chạy ô 4, Colab in ra: `✅ Đã kết nối cổng. LINK CỐ ĐỊNH (dùng mãi): …`

## Ứng dụng Android
Mở app → **⚙ Máy chủ** → dán link cố định → **Lưu & mở**. Không bao giờ phải đổi link nữa.

## Lưu ý
- Gói miễn phí của Cloudflare giới hạn mỗi lần tải video lên tối đa **100 MB**.
- Nên đặt thêm secret `APP_PASSWORD` trên Colab để link cố định có mật khẩu.
- Cập nhật phần mềm: Claude đẩy bản sửa lên GitHub → Colab tự lấy bản mới khi chạy ô 1; cổng Cloudflare tự cập nhật.
