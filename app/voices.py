"""Kho giọng đọc tiếng Việt.

- edge:   Microsoft Edge TTS (miễn phí). Có 2 giọng Việt gốc (HoaiMy - nữ, NamMinh - nam);
          các "nhân vật" kiểu CapCut được tạo bằng cách chỉnh tốc độ/cao độ.
- fpt:    FPT.AI TTS, 9 giọng Việt bản xứ Bắc/Trung/Nam (cần FPT_API_KEY).
- gtts:   Google TTS (dự phòng cuối cùng).

Mã giọng có dạng  "<provider>:<id>".
"""
from __future__ import annotations

import asyncio
import hashlib
import shutil
import time
from pathlib import Path

import httpx

from .config import CACHE_DIR, FPT_API_KEY

# id, tên hiển thị, giới tính, mô tả, provider, tham số
_EDGE = [
    ("hoaimy", "Hoài My", "female", "Nữ, chuẩn, rõ ràng", "vi-VN-HoaiMyNeural", 0, 0),
    ("namminh", "Nam Minh", "male", "Nam, chuẩn, rõ ràng", "vi-VN-NamMinhNeural", 0, 0),
    ("nu-tre", "Cô gái trẻ trung", "female", "Nữ, cao, vui tươi", "vi-VN-HoaiMyNeural", 6, 12),
    ("nu-diu", "Chị dịu dàng", "female", "Nữ, chậm, ấm", "vi-VN-HoaiMyNeural", -8, -4),
    ("nu-review", "Reviewer nhanh", "female", "Nữ, nhanh, năng động", "vi-VN-HoaiMyNeural", 15, 6),
    ("be-gai", "Bé gái", "female", "Giọng trẻ em", "vi-VN-HoaiMyNeural", 4, 30),
    ("nam-tram", "Anh trầm ấm", "male", "Nam, trầm, kể chuyện", "vi-VN-NamMinhNeural", -6, -10),
    ("nam-nangdong", "Chàng trai năng động", "male", "Nam, nhanh, sôi nổi", "vi-VN-NamMinhNeural", 12, 6),
    ("nam-mc", "MC quảng cáo", "male", "Nam, dứt khoát", "vi-VN-NamMinhNeural", 6, -3),
    ("ong-lao", "Ông kể chuyện", "male", "Nam, rất trầm, chậm", "vi-VN-NamMinhNeural", -14, -22),
]

_FPT = [
    ("banmai", "Ban Mai", "female", "Nữ miền Bắc"),
    ("thuminh", "Thu Minh", "female", "Nữ miền Bắc"),
    ("leminh", "Lê Minh", "male", "Nam miền Bắc"),
    ("myan", "Mỹ An", "female", "Nữ miền Trung"),
    ("ngoclam", "Ngọc Lam", "female", "Nữ miền Trung"),
    ("giahuy", "Gia Huy", "male", "Nam miền Trung"),
    ("lannhi", "Lan Nhi", "female", "Nữ miền Nam"),
    ("linhsan", "Linh San", "female", "Nữ miền Nam"),
    ("minhquang", "Minh Quang", "male", "Nam miền Nam"),
]

SAMPLE_TEXT = "Xin chào các bạn, hôm nay mình sẽ giới thiệu một sản phẩm cực kỳ hay ho nhé!"


def list_voices() -> list[dict]:
    out = []
    for vid, name, g, desc, *_ in _EDGE:
        out.append({"id": f"edge:{vid}", "name": name, "gender": g, "desc": desc, "provider": "Edge (miễn phí)"})
    if FPT_API_KEY:
        for vid, name, g, desc in _FPT:
            out.append({"id": f"fpt:{vid}", "name": name, "gender": g, "desc": desc, "provider": "FPT.AI"})
    out.append({"id": "gtts:vi", "name": "Google cơ bản", "gender": "female", "desc": "Giọng máy, dự phòng",
                "provider": "Google"})
    return out


def _edge_params(vid: str):
    # chấp nhận cả tên đầy đủ kiểu "vi-VN-HoaiMyNeural"
    for v in _EDGE:
        if v[0] == vid or (v[4] == vid and v[5] == 0 and v[6] == 0):
            return v[4], v[5], v[6]
    return vid, 0, 0


async def _edge_save(text, voice, rate_pct, pitch_hz, path):
    import edge_tts
    rate = f"{int(round(rate_pct)):+d}%"
    pitch = f"{int(round(pitch_hz)):+d}Hz"
    await edge_tts.Communicate(text, voice, rate=rate, pitch=pitch).save(str(path))


def _fpt_save(text, voice, speed, path):
    if not FPT_API_KEY:
        raise RuntimeError("Chưa cấu hình FPT_API_KEY")
    sp = max(-3, min(3, int(round((speed - 1.0) * 6))))
    r = httpx.post("https://api.fpt.ai/hmi/tts/v5", content=text.encode("utf-8"), timeout=30,
                   headers={"api-key": FPT_API_KEY, "voice": voice, "speed": str(sp), "format": "mp3"})
    r.raise_for_status()
    link = r.json().get("async")
    if not link:
        raise RuntimeError(f"FPT.AI trả lỗi: {r.text[:200]}")
    for _ in range(40):  # file được tạo bất đồng bộ
        time.sleep(1.0)
        a = httpx.get(link, timeout=30)
        if a.status_code == 200 and len(a.content) > 1000:
            Path(path).write_bytes(a.content)
            return
    raise RuntimeError("FPT.AI tạo audio quá lâu")


def synth(text: str, voice_id: str, path: Path, speed: float = 1.0) -> Path:
    """Tạo 1 file mp3. Tự động lùi về gTTS nếu nhà cung cấp lỗi."""
    provider, _, vid = voice_id.partition(":")
    try:
        if provider == "edge":
            voice, rate, pitch = _edge_params(vid)
            rate = rate + (speed - 1.0) * 100
            asyncio.run(_edge_save(text, voice, rate, pitch, path))
            return path
        if provider == "fpt":
            _fpt_save(text, vid, speed, path)
            return path
    except Exception as e:  # noqa: BLE001
        print(f"TTS {voice_id} lỗi ({str(e)[:120]}), dùng gTTS thay thế")
    from gtts import gTTS
    gTTS(text, lang="vi", slow=False).save(str(path))
    return path


def preview(voice_id: str) -> Path:
    key = hashlib.md5(voice_id.encode()).hexdigest()[:12]
    p = CACHE_DIR / f"preview_{key}.mp3"
    if not p.exists() or p.stat().st_size < 1000:
        tmp = p.with_suffix(".tmp.mp3")
        synth(SAMPLE_TEXT, voice_id, tmp)
        shutil.move(tmp, p)
    return p
