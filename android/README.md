# Ứng dụng Android "Video Tiếng Việt"

Được tạo bởi **Ngô Thị Hồng Hạnh**. Ứng dụng là bảng điều khiển trên điện thoại; phần xử lý video (AI nhận dạng giọng,
dịch, dựng video) chạy trên máy chủ Google Colab / VPS.

## Cài đặt
1. Chép `VideoTiengViet.apk` vào điện thoại (Zalo/Drive/cáp USB) rồi mở file.
2. Khi được hỏi, cho phép **Cài đặt ứng dụng không rõ nguồn gốc** cho ứng dụng đang mở file (Quản lý tệp/Drive/Zalo).
3. Nếu Google Play Protect cảnh báo "ứng dụng chưa xác minh" → **Chi tiết khác → Vẫn cài đặt**
   (vì ứng dụng tự build, không đăng trên CH Play).

## Dùng
- Lần đầu mở: dán link máy chủ `https://….trycloudflare.com` (lấy từ ô "4. Chạy web" trên Colab).
- Link hết hạn (lỗi 1033/530): app tự hiện màn hình đổi link → chạy ô "5. Lấy link mới" trên Colab rồi dán.
- Trong app Xiaohongshu: **Chia sẻ → Video Tiếng Việt** để gửi link video sang app.
- Video tải về: thư mục **Phim/VideoViet** (hiện trong Bộ sưu tập).
- Nút **⚙ Máy chủ** ở góc trên để đổi link.

## Build lại (Ubuntu/Linux)
```bash
sudo apt install default-jdk android-sdk-platform-23 android-sdk-build-tools dalvik-exchange apksigner zipalign
./build.sh            # ra build/VideoTiengViet.apk
```
Giữ nguyên file `videoviet.keystore` (mật khẩu `videoviet`) để các bản cập nhật cài đè được lên bản cũ.
Muốn tăng phiên bản: sửa `--version-code`/`--version-name` trong build.sh và `android:versionCode` trong AndroidManifest.xml.
