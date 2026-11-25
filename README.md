# Video chuyển đổi Tiếng Việt (web tool)

Phần mềm được tạo bởi **Ngô Thị Hồng Hạnh**.

Dán link video Xiaohongshu → nhận về video:
- **Lồng tiếng Việt** (10+ giọng nam/nữ có nghe thử, thêm 9 giọng bản xứ Bắc/Trung/Nam nếu có FPT.AI key)
- **Dịch chữ Trung trên hình** sang chữ Việt ở đúng vị trí, chọn **kiểu chữ** (23 kiểu: khung màu, viền, sticker viền đôi, đổ bóng, neon, chuyển màu, giữ màu gốc) và **phông chữ** (24 font Google đủ dấu tiếng Việt + font riêng của bạn) giống CapCut, có xem trước trực tiếp
- Khung chữ **vừa đúng cỡ chữ gốc** (không che hình) hoặc **to, dễ đọc**; chọn **nền màu tuỳ ý** hoặc **không nền**
- **Nhạc nền**: 6 bản nhạc do tool tự sáng tác (không bản quyền bên thứ ba), hoặc tải nhạc bạn có giấy phép; tự giảm nhạc khi có giọng nói
- Nút **✨ Tạo hook & hashtag** cho TikTok/Facebook (Claude nếu có API key, không thì dùng mẫu), có lọc từ ngữ dễ vi phạm nguyên tắc cộng đồng
- **Chữ ký bản quyền** (vd `@Ngô Thị Hồng Hạnh`): bật/tắt, chọn kiểu chữ, phông, vị trí, độ rõ và hiệu ứng (đứng yên, mờ ảo, chạy ngang, trôi nảy, đổi góc, hiện/ẩn, nảy vào)
- **Chất lượng cao**: tải bản nét nhất, nâng lên 1080p (Lanczos + làm nét), giữ đúng màu (BT.709) và FPS gốc, H.264 High CRF 14–16, AAC 256 kbps 48 kHz stereo, âm lượng chuẩn -14 LUFS
- **Xoá logo / watermark Xiaohongshu** (chữ 小红书, ID 小红书号, khối logo đỏ, kể cả khi logo nhảy góc)
- **Cắt đoạn kết** có logo Xiaohongshu
- Xuất kèm phụ đề `.srt`
- **🎬 Sáng tạo video mới** lấy cảm hứng từ video (không dịch nguyên văn): AI viết kịch bản mới chia cảnh, bạn sửa từng cảnh; hình lấy từ file bạn tải lên (tự quay hoặc video Xiaohongshu), video gốc đã xoá logo + chữ Trung, rồi kho miễn phí bản quyền Pexels/Pixabay (`PEXELS_API_KEY`, `PIXABAY_API_KEY`)

## Cấu trúc

```
app/
  main.py        API (FastAPI) + phục vụ giao diện
  jobs.py        hàng đợi job, lưu trạng thái ra data/jobs/<id>/job.json
  pipeline.py    các bước: tải → dò chữ/logo → nhận dạng giọng → dịch → lồng tiếng → xuất video
  downloader.py  tải video từ xhslink.com / xiaohongshu.com (ưu tiên bản gốc không watermark)
  speech.py      faster-whisper, dịch (Google / Claude), ghép giọng khớp thời gian
  voices.py      kho giọng: Edge TTS, FPT.AI, gTTS
  onscreen.py    OCR (RapidOCR), theo dõi chữ, xoá chữ/logo, vẽ chữ Việt, dò outro
  music.py       nhạc nền tự tổng hợp + trộn nhạc (ducking)
  signature.py   chữ ký bản quyền + hiệu ứng chuyển động
  creator.py     sáng tạo video mới: kịch bản AI + ghép cảnh (file của bạn / video gốc / Pexels / Pixabay)
  captions.py    tạo hook, caption, hashtag + kiểm tra từ ngữ vi phạm
  textstyle.py   kiểu chữ + phông chữ (thêm kiểu mới: sửa PRESETS, thêm font: sửa FONTS)
  static/index.html  giao diện web
gateway/         cổng link cố định trên Cloudflare Workers (wrangler.jsonc ở thư mục gốc)
fonts/           (tuỳ chọn) đặt font .ttf/.otf của bạn vào đây, sẽ hiện trong mục "Font của bạn"
colab_run_web.ipynb  chạy web trên Google Colab GPU, có link public
```

## Chạy

### Link cố định qua Cloudflare (khuyên dùng với Colab)
Xem `HUONG-DAN-CLOUDFLARE.md`: cổng `gateway/` (Cloudflare Worker) cho link cố định `https://video-tieng-viet.<tài-khoản>.workers.dev`, Colab tự báo link mới cho cổng.

### Cách 0 — Hugging Face Spaces (miễn phí, link cố định, không cần Colab)
Xem `hf_space/README.md`: tải 3 file `Dockerfile`, `README.md`, `xhs2vi.zip` lên một Space Docker, đặt secret `APP_PASSWORD`.

### Cách 1 — Google Colab (miễn phí, có GPU)
Nén thư mục thành `xhs2vi.zip`, mở `colab_run_web.ipynb` trên Colab, chạy từng ô, mở link `trycloudflare.com` được in ra.

### Cách 2 — Máy cá nhân / VPS
Cần Python 3.10+ và ffmpeg.
```bash
pip install -r requirements.txt
cp .env.example .env      # sửa nếu cần
uvicorn app.main:app --host 0.0.0.0 --port 8000
```
Mở http://localhost:8000

### Cách 3 — Docker
```bash
cp .env.example .env
docker compose up -d --build
```

## Cấu hình (`.env`)

| Biến | Ý nghĩa |
|---|---|
| `WHISPER_MODEL` | `small` / `medium` / `large-v3-turbo` / `large-v3`. CPU nên dùng `small`, GPU dùng `large-v3-turbo` (nhanh, gần bằng `large-v3`) |
| `ANTHROPIC_API_KEY` | Bật dịch bằng Claude (tự nhiên, đúng ngữ cảnh hơn Google Translate) |
| `CLAUDE_MODEL` | Mặc định `claude-opus-5-5` |
| `FPT_API_KEY` | Bật 9 giọng Việt bản xứ của FPT.AI |
| `XHS_COOKIE` | Cookie đăng nhập xiaohongshu.com, dùng khi link báo cần đăng nhập |
| `PEXELS_API_KEY`, `PIXABAY_API_KEY` | Kho video miễn phí cho tính năng Sáng tạo video mới |
| `MAX_WORKERS` | Số video xử lý song song (máy 1 GPU để 1) |

Giữ nhạc nền mà bỏ giọng Trung: `pip install demucs`, rồi kéo thanh "Giữ âm thanh gốc / nhạc nền" > 0.

## Khi kết quả chưa ưng ý
- **Link không tải được**: Xiaohongshu hay chặn máy chủ ở nước ngoài/IP datacenter. Thử đặt `XHS_COOKIE`, hoặc tải video về máy rồi dùng nút *tải file lên*.
- **Còn sót logo**: xem "Ảnh kiểm tra" trong kết quả (khung đỏ = logo đã dò thấy). Logo không có khung → nhập *Vùng luôn xoá*, ví dụ góc trên phải `0.7,0,1,0.1`.
- **Còn sót chữ Trung**: giảm *Ngưỡng tin cậy OCR*, tăng *Tần suất dò chữ*.
- **Chữ Việt to/nhỏ**: chỉnh *Cỡ chữ Việt*.
- **Font**: font Google được tải tự động lần đầu dùng (từ raw.githubusercontent.com) vào `data/fonts`. Tải sẵn tất cả: `python -m app.textstyle`. Font riêng: bấm "＋ Tải font của bạn" trên giao diện hoặc bỏ vào thư mục `fonts/`.
- **Muốn chữ nằm trong khung màu tuỳ ý**: chọn kiểu bất kỳ rồi tick "Màu nền" và chọn màu.

## Lưu ý
- **Nhạc viral/xu hướng** trên TikTok, Facebook đều có bản quyền, tool không chèn sẵn được. Cách hợp lệ: xuất video không nhạc (hoặc nhạc có sẵn của tool), rồi chọn nhạc trong app khi đăng: TikTok → Thư viện âm nhạc thương mại (Commercial Music Library, bắt buộc với tài khoản doanh nghiệp), Facebook/Instagram → Thư viện âm thanh. Nhạc tải về được phép dùng thương mại: Pixabay Music, YouTube Audio Library, Facebook Sound Collection (xem điều khoản từng nguồn).
- **Hook & hashtag** giúp tối ưu nội dung nhưng không nền tảng nào cho phép "đảm bảo lên xu hướng"; hãy đọc lại trước khi đăng.
Chỉ dùng cho video bạn có quyền sử dụng (của chính bạn, hoặc được tác giả cho phép). Xoá watermark và đăng lại nội dung của người khác có thể vi phạm bản quyền và điều khoản của các nền tảng.
