"""In câu hook lên những giây đầu của video đã xuất (không cần xử lý lại từ đầu)."""
from __future__ import annotations

import subprocess
from pathlib import Path

from . import textstyle
from .utils import probe_video, run, video_encode_args

# vị trí theo tỉ lệ chiều cao, tránh vùng giao diện TikTok/Reels (trên cùng ~10%, dưới cùng ~25%)
POSITIONS = {"top": ("Phía trên", 0.17), "center": ("Giữa màn hình", 0.45), "lower": ("Phía dưới", 0.64)}


def _size(path):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                   "stream=width,height", "-of", "csv=p=0", str(path)], text=True)
    w, h = out.strip().split(",")[:2]
    return int(w), int(h)


def burn(src: Path, out: Path, text: str, preset="yellow_box", font="bevietnam", seconds=3.0, position="center",
         bg_mode="preset", bg_color=""):
    W, H = _size(src)
    st = textstyle.resolve_style(preset, "", bg_color, "", -1, bg_mode)
    size = max(20, int(W * 0.075))
    fnt, sz, lines = textstyle.fit_text(text.strip(), font, size, W * 0.88, 3, st)
    img = textstyle.render_text(lines, fnt, sz, st)
    png = out.with_suffix(".hook.png")
    img.save(png)
    seconds = max(1.0, min(8.0, float(seconds)))
    yr = POSITIONS.get(position, POSITIONS["center"])[1]
    y = max(0, int(H * yr - img.height / 2))
    fo = max(0.0, seconds - 0.35)
    flt = (f"[1:v]format=rgba,fade=t=in:st=0:d=0.25:alpha=1,fade=t=out:st={fo:.2f}:d=0.35:alpha=1[h];"
           f"[0:v][h]overlay=x=(W-w)/2:y={y}:enable='between(t,0,{seconds:.2f})'[v]")
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-loop", "1", "-t", f"{seconds:.2f}", "-i", png,
         "-filter_complex", flt, "-map", "[v]", "-map", "0:a?", *video_encode_args("high", probe_video(src)["color"]),
         "-c:a", "copy", out])
    png.unlink(missing_ok=True)
    return out
