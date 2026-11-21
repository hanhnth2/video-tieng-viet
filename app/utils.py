from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path


def run(cmd, cwd=None, timeout=None):
    r = subprocess.run([str(c) for c in cmd], cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"Lệnh lỗi: {' '.join(map(str, cmd[:3]))}...\n{r.stderr[-1500:]}")
    return r.stdout


def probe_duration(p) -> float:
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                   "-of", "default=nw=1:nk=1", str(p)])
    return float(out.strip())


def has_audio(p) -> bool:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
                          "stream=index", "-of", "csv=p=0", str(p)], capture_output=True, text=True).stdout
    return bool(out.strip())


def fmt_ts(sec: float) -> str:
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(path, cues):
    blocks = []
    for i, (st, en, t) in enumerate(cues, 1):
        w = "\n".join(textwrap.wrap(t, 42)) or t
        blocks.append(f"{i}\n{fmt_ts(st)} --> {fmt_ts(en)}\n{w}\n")
    Path(path).write_text("\n".join(blocks), encoding="utf-8")


# ---------------- Chất lượng xuất video ----------------
QUALITY = {
    # crf càng thấp càng nét (file to hơn); preset càng chậm nén càng hiệu quả
    "max": ("14", "slow"),
    "high": ("18", "medium"),   # mắt thường gần như không khác crf 16, file nhẹ hơn ~40% -> tải về nhanh, ít bị đứt
    "fast": ("20", "veryfast"),
}


def probe_video(p) -> dict:
    """fps dạng phân số chính xác (vd 30000/1001) + thông tin màu của video gốc."""
    import json as _json
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height,avg_frame_rate,r_frame_rate,color_space,color_primaries,color_transfer",
                          "-of", "json", str(p)], capture_output=True, text=True).stdout
    try:
        s = _json.loads(out)["streams"][0]
    except Exception:  # noqa: BLE001
        return {"fps_str": None, "color": "bt709"}
    fr = s.get("avg_frame_rate") or s.get("r_frame_rate") or "0/0"
    if fr in ("0/0", "0/1"):
        fr = s.get("r_frame_rate")
    cs = s.get("color_space") or ""
    color = "bt601" if cs in ("smpte170m", "bt470bg") else "bt709"
    return {"fps_str": fr, "color": color, "width": s.get("width"), "height": s.get("height")}


def video_encode_args(quality="high", color="bt709", fps_str=None):
    crf, preset = QUALITY.get(quality, QUALITY["high"])
    tags = (["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709"] if color == "bt709"
            else ["-colorspace", "smpte170m", "-color_primaries", "smpte170m", "-color_trc", "smpte170m"])
    args = ["-c:v", "libx264", "-preset", preset, "-crf", crf, "-profile:v", "high", "-pix_fmt", "yuv420p",
            "-maxrate", "25M", "-bufsize", "50M", *tags, "-movflags", "+faststart"]
    if fps_str:
        args += ["-r", fps_str]
    return args


AUDIO_ARGS = ["-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-ac", "2"]


def video_duration(p) -> float:
    """Thời lượng của riêng luồng HÌNH (không lấy theo luồng tiếng)."""
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=duration:format=duration", "-of", "default=nw=1", str(p)],
                         capture_output=True, text=True).stdout
    vals = {}
    for line in out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            try:
                vals.setdefault(k, float(v))
            except ValueError:
                pass
    return vals.get("duration") or probe_duration(p)


def mux_exact(video_only, audio, out, video_args=None):
    """Ghép tiếng vào hình với độ dài ĐÚNG BẰNG phần hình: tiếng dài hơn thì cắt, ngắn hơn thì bù im lặng.

    Không dùng -shortest (ffmpeg 4.x trên Colab đôi khi để thừa vài giây tiếng -> cuối video đứng hình).
    """
    dur = video_duration(video_only)
    vargs = video_args or ["-c:v", "copy"]
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", video_only, "-i", audio, "-map", "0:v:0", "-map", "1:a:0",
         *vargs, "-af", "apad", "-t", f"{dur:.3f}", *AUDIO_ARGS, "-movflags", "+faststart", out])
    return dur
