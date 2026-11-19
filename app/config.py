"""Cấu hình chung và tuỳ chọn cho từng job."""
from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from pathlib import Path


def _load_dotenv() -> None:
    p = Path(__file__).resolve().parent.parent / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()

DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parent.parent / "data")).resolve()
JOBS_DIR = DATA_DIR / "jobs"
CACHE_DIR = DATA_DIR / "cache"
JOBS_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)

WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "medium")
MAX_WORKERS = int(os.environ.get("MAX_WORKERS", "1"))
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5-5")
FPT_API_KEY = os.environ.get("FPT_API_KEY", "")
XHS_COOKIE = os.environ.get("XHS_COOKIE", "")


@dataclass
class JobOptions:
    # ---- Giọng nói ----
    voice: str = "edge:hoaimy"
    speed: float = 1.0               # tốc độ đọc cơ bản (0.8 - 1.3)
    max_speedup: float = 1.6         # tăng tốc tối đa khi câu dịch dài hơn câu gốc
    bg_volume: float = 0.0           # giữ âm thanh gốc (0 = tắt). Có demucs: chỉ giữ nhạc nền
    separate_vocals: bool = True     # dùng demucs tách nhạc nền nếu có cài
    translator: str = "auto"         # auto | google | claude
    # ---- Chữ trên hình ----
    replace_text: bool = True
    text_scope: str = "overlay"      # overlay = chỉ tiêu đề/phụ đề chèn lên video | all = mọi chữ Trung
    review_text: bool = False        # dừng lại cho người dùng duyệt chữ trước khi xuất
    text_preset: str = "yellow_box"  # xem textstyle.PRESETS ("original" = giữ màu chữ gốc)
    font: str = "bevietnam"          # xem textstyle.FONTS, hoặc "custom:<tên file>"
    text_color: str = ""             # "" = theo kiểu chữ
    bg_color: str = ""
    stroke_color: str = ""
    bg_opacity: float = -1.0         # -1 = theo kiểu chữ, 0..1
    bg_mode: str = "preset"          # preset | none (không nền) | color (nền màu bg_color)
    fit_mode: str = "fit"            # fit = khung vừa chữ gốc, không che hình | large = to, dễ đọc
    font_scale: float = 0.8
    cover_mode: str = "box"          # box | mask | solid
    sample_fps: float = 4.0
    min_ocr_conf: float = 0.3
    # ---- Logo Xiaohongshu ----
    remove_logo: bool = True
    trim_outro: bool = True
    manual_regions: str = ""         # "x1,y1,x2,y2; ..." tỉ lệ 0-1
    # ---- Nhạc nền ----
    music: str = ""                  # "" = không chèn | id nhạc có sẵn | "custom:<file>"
    music_volume: float = 0.25
    music_duck: bool = True          # tự giảm nhạc khi có giọng nói
    # ---- Chữ ký / tên chủ sở hữu ----
    wm_enabled: bool = False
    wm_text: str = ""                # vd "@Ngô Thị Hồng Hạnh"
    wm_preset: str = "shadow"        # kiểu chữ (textstyle.PRESETS)
    wm_font: str = "bevietnam"
    wm_color: str = ""               # "" = theo kiểu chữ
    wm_size: float = 0.045           # cỡ chữ theo cạnh ngắn của video
    wm_opacity: float = 0.85
    wm_effect: str = "static"        # xem signature.EFFECTS
    wm_position: str = "bottom-right"
    # ---- Chất lượng xuất ----
    quality: str = "high"            # max | high | fast
    upscale: bool = True             # nâng lên 1080p (chuẩn TikTok/Reels) nếu video gốc nhỏ hơn
    loudnorm: bool = True            # chuẩn độ to âm thanh -14 LUFS
    # ---- Khác ----
    burn_subs: bool = False

    @classmethod
    def from_dict(cls, d: dict) -> "JobOptions":
        o = cls()
        for k, v in (d or {}).items():
            if not hasattr(o, k) or v is None:
                continue
            cur = getattr(o, k)
            try:
                if isinstance(cur, bool):
                    v = v if isinstance(v, bool) else str(v).lower() in ("1", "true", "on", "yes")
                elif isinstance(cur, float):
                    v = float(v)
                elif isinstance(cur, int):
                    v = int(v)
                else:
                    v = str(v)
            except (TypeError, ValueError):
                continue
            setattr(o, k, v)
        o.speed = min(1.5, max(0.6, o.speed))
        o.max_speedup = min(2.0, max(1.0, o.max_speedup))
        o.bg_volume = min(1.0, max(0.0, o.bg_volume))
        o.font_scale = min(1.4, max(0.4, o.font_scale))
        o.sample_fps = min(10.0, max(1.0, o.sample_fps))
        o.music_volume = min(1.0, max(0.0, o.music_volume))
        o.wm_size = min(0.12, max(0.015, o.wm_size))
        o.wm_text = o.wm_text[:60]
        return o

    def to_dict(self) -> dict:
        return asdict(self)
