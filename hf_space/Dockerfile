# Máy chủ "Video chuyển đổi Tiếng Việt" (tạo bởi Ngô Thị Hồng Hạnh) trên Hugging Face Spaces (CPU miễn phí).
# Chỉ cần tải 3 file lên Space: Dockerfile, README.md, xhs2vi.zip
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg fonts-noto-core fonts-wqy-zenhei libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Hugging Face chạy container bằng user id 1000
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/home/user/data \
    WHISPER_MODEL=small \
    MAX_WORKERS=1
WORKDIR /home/user

COPY --chown=user xhs2vi.zip /home/user/xhs2vi.zip
RUN python -m zipfile -e xhs2vi.zip . && rm xhs2vi.zip
WORKDIR /home/user/xhs2vi

RUN pip install --no-cache-dir --user -r requirements.txt

# Tải sẵn mô hình nhận dạng giọng, mô hình dò chữ và font để mở web nhanh hơn
# (bước nào lỗi thì bỏ qua: sẽ tự tải khi dùng lần đầu)
RUN (python -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8')" || true) \
 && (python -c "from rapidocr import RapidOCR; RapidOCR()" || true) \
 && (python -m app.textstyle > /dev/null || true)

EXPOSE 7860
# Nếu Space có bộ nhớ lâu dài (/data) thì lưu lịch sử video ở đó
CMD ["sh", "-c", "if [ -w /data ]; then export DATA_DIR=/data; fi; exec uvicorn app.main:app --host 0.0.0.0 --port 7860"]
