"""Nhạc nền.

- Nhạc có sẵn: do tool tự tổng hợp bằng code (không lấy mẫu từ bài hát nào)
  -> không có bản quyền của bên thứ ba, dùng thương mại thoải mái.
- Nhạc của bạn: tải lên các bản nhạc bạn có giấy phép (Pixabay Music, YouTube Audio Library,
  Facebook Sound Collection, nhạc mua bản quyền...). Đặt trong data/music/custom hoặc thư mục music/.
- mix_into(): lặp nhạc theo độ dài video, fade in/out, tự giảm âm lượng khi có giọng nói (ducking).
"""
from __future__ import annotations

import re
import subprocess
import threading
from pathlib import Path

import numpy as np

from .config import DATA_DIR

SR = 44100
MUSIC_DIR = DATA_DIR / "music"
BUILTIN_DIR = MUSIC_DIR / "builtin"
CUSTOM_DIRS = [Path(__file__).resolve().parent.parent / "music", MUSIC_DIR / "custom"]
for d in (BUILTIN_DIR, MUSIC_DIR / "custom"):
    d.mkdir(parents=True, exist_ok=True)
_gen_lock = threading.Lock()

# id: (tên, mô tả, bpm, hợp âm (midi gốc + loại), kiểu trống, nhạc cụ chính)
TRACKS = {
    "vui-tuoi": ("Vui tươi", "Pop sáng, hợp review sản phẩm", 118,
                 [(60, "maj"), (67, "maj"), (69, "min"), (65, "maj")], "pop", "pluck"),
    "lofi": ("Lo-fi chill", "Nhẹ, thư giãn, hợp vlog đời thường", 80,
             [(65, "maj7"), (64, "min7"), (62, "min7"), (60, "maj7")], "lofi", "keys"),
    "soi-dong": ("Sôi động", "Nhịp mạnh, hợp video nhanh, biến hình", 126,
                 [(57, "min"), (65, "maj"), (60, "maj"), (67, "maj")], "edm", "stab"),
    "nhe-nhang": ("Nhẹ nhàng", "Guitar mộc, hợp làm đẹp, nấu ăn", 92,
                  [(60, "maj"), (57, "min"), (65, "maj"), (67, "maj")], "soft", "guitar"),
    "hoi-hop": ("Hồi hộp", "Kịch tính, hợp unbox, bất ngờ", 100,
                [(62, "min"), (58, "maj"), (55, "min"), (57, "maj")], "tension", "pulse"),
    "dang-yeu": ("Đáng yêu", "Ukulele vui nhộn, hợp thú cưng, trẻ em", 112,
                 [(60, "maj"), (65, "maj"), (67, "maj"), (60, "maj")], "clap", "uke"),
}
CHORD = {"maj": [0, 4, 7], "min": [0, 3, 7], "maj7": [0, 4, 7, 11], "min7": [0, 3, 7, 10]}


# ---------------- Tổng hợp âm thanh ----------------
def _f(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def _env(n, a=0.005, r=0.3, sr=SR):
    t = np.arange(n) / sr
    e = np.minimum(1.0, t / max(a, 1e-4)) * np.exp(-t / max(r, 1e-4))
    return e.astype(np.float32)


def _lowpass(x, cutoff):
    X = np.fft.rfft(x)
    fr = np.fft.rfftfreq(len(x), 1 / SR)
    X *= 1.0 / np.sqrt(1.0 + (fr / cutoff) ** 4)
    return np.fft.irfft(X, len(x)).astype(np.float32)


def _tone(freq, dur, kind, rng):
    n = int(dur * SR)
    t = np.arange(n) / SR
    if kind == "pluck":
        y = sum(np.sin(2 * np.pi * k * freq * t) * np.exp(-t * (4 + 3 * k)) / k ** 1.2 for k in range(1, 6))
    elif kind in ("guitar", "uke"):
        dec = 2.5 if kind == "guitar" else 5.0
        y = sum(np.sin(2 * np.pi * k * freq * t + rng.uniform(0, 1)) * np.exp(-t * (dec + 1.6 * k)) / k
                for k in range(1, 8))
    elif kind == "keys":
        y = (np.sin(2 * np.pi * freq * t) + 0.35 * np.sin(4 * np.pi * freq * t)) * np.exp(-t * 1.6)
        y *= 1 + 0.15 * np.sin(2 * np.pi * 5 * t)  # tremolo nhẹ
    elif kind == "pad":
        y = sum(np.sin(2 * np.pi * freq * (1 + d) * t) for d in (-0.004, 0, 0.004)) / 3
        y *= np.minimum(1, t / 0.4) * np.minimum(1, (dur - t) / 0.4).clip(0)
    elif kind == "stab":
        saw = sum(np.sin(2 * np.pi * k * freq * t) / k for k in range(1, 9))
        y = saw * np.exp(-t * 9)
    elif kind == "bass":
        y = np.tanh(1.8 * np.sin(2 * np.pi * freq * t)) * np.exp(-t * 3.5)
    elif kind == "pulse":
        y = np.tanh(2.5 * np.sin(2 * np.pi * freq * t)) * np.exp(-t * 7)
    else:
        y = np.sin(2 * np.pi * freq * t) * np.exp(-t * 3)
    return (y * _env(n, 0.004, dur)).astype(np.float32)


def _kick(rng):
    n = int(0.35 * SR)
    t = np.arange(n) / SR
    f = 45 + 110 * np.exp(-t * 30)
    return (np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 9)).astype(np.float32)


def _snare(rng, soft=False):
    n = int(0.22 * SR)
    t = np.arange(n) / SR
    noise = np.diff(rng.standard_normal(n + 1)).astype(np.float32) * 0.5
    y = noise * np.exp(-t * 18) + 0.4 * np.sin(2 * np.pi * 185 * t) * np.exp(-t * 25)
    return (y * (0.5 if soft else 1.0)).astype(np.float32)


def _hat(rng, open_=False):
    n = int((0.18 if open_ else 0.05) * SR)
    t = np.arange(n) / SR
    noise = np.diff(np.diff(rng.standard_normal(n + 2))).astype(np.float32) * 0.25
    return (noise * np.exp(-t * (14 if open_ else 70))).astype(np.float32)


def _clap(rng):
    n = int(0.2 * SR)
    t = np.arange(n) / SR
    noise = np.diff(rng.standard_normal(n + 1)).astype(np.float32) * 0.5
    bursts = sum(np.exp(-np.maximum(0, t - d) * 60) * (t >= d) for d in (0, 0.01, 0.02))
    return (noise * bursts * np.exp(-t * 10) * 0.6).astype(np.float32)


def _add(buf, sig, pos, gain=1.0):
    p = int(pos * SR)
    if p >= len(buf):
        return
    s = sig[: len(buf) - p]
    buf[p:p + len(s)] += s * gain


def synth_track(tid: str, bars=16, seed=7) -> np.ndarray:
    name, _, bpm, prog, drums, lead = TRACKS[tid]
    rng = np.random.default_rng(seed)
    beat = 60.0 / bpm
    bar = 4 * beat
    total = bars * bar
    n = int((total + 1.0) * SR)
    mel = np.zeros(n, np.float32)
    bas = np.zeros(n, np.float32)
    drm = np.zeros(n, np.float32)
    pad = np.zeros(n, np.float32)
    kick, hat, hato, clap = _kick(rng), _hat(rng), _hat(rng, True), _clap(rng)
    for b in range(bars):
        root, kind = prog[b % len(prog)]
        notes = [root + i for i in CHORD[kind]]
        t0 = b * bar
        intro = b < 2
        # --- pad / hợp âm nền ---
        for m in notes:
            _add(pad, _tone(_f(m), bar, "pad", rng), t0, 0.10)
        # --- nhạc cụ chính ---
        if lead in ("pluck", "guitar", "uke"):
            pattern = [0, 1, 2, 1, 3 % len(notes), 1, 2, 1] if lead != "uke" else [0, 2, 1, 2, 0, 2, 1, 2]
            step = bar / 8
            for i, k in enumerate(pattern):
                m = notes[k % len(notes)] + (12 if lead == "pluck" and i % 4 == 2 else 0)
                _add(mel, _tone(_f(m), step * 2.5, lead, rng), t0 + i * step, 0.22)
        elif lead == "keys":
            for hit in (0, 1.5, 2.5):
                for m in notes:
                    _add(mel, _tone(_f(m), beat * 1.8, "keys", rng), t0 + hit * beat + rng.uniform(0, 0.015), 0.11)
        elif lead == "stab":
            for i in range(8):
                if i % 2 == 1:
                    for m in notes:
                        _add(mel, _tone(_f(m + 12), beat * 0.4, "stab", rng), t0 + i * beat / 2, 0.06)
        elif lead == "pulse":
            for i in range(8):
                _add(mel, _tone(_f(notes[i % len(notes)] + 12), beat * 0.45, "pulse", rng), t0 + i * beat / 2, 0.08)
        # --- bass ---
        bf = _f(root - 24)
        if drums == "edm":
            for i in range(4):
                _add(bas, _tone(bf, beat * 0.45, "bass", rng), t0 + i * beat + beat / 2, 0.35)
        elif drums in ("lofi", "soft"):
            _add(bas, _tone(bf, beat * 2, "bass", rng), t0, 0.3)
            _add(bas, _tone(bf, beat * 1.5, "bass", rng), t0 + 2.5 * beat, 0.25)
        else:
            for i in range(8):
                _add(bas, _tone(bf, beat * 0.5, "bass", rng), t0 + i * beat / 2, 0.22)
        # --- trống ---
        swing = beat * 0.08 if drums == "lofi" else 0
        for i in range(8):
            tt = t0 + i * beat / 2 + (swing if i % 2 else 0)
            if drums in ("pop", "edm"):
                if i % 2 == 0:
                    _add(drm, kick, tt, 0.9)
                _add(drm, hato if (drums == "edm" and i % 2) else hat, tt, 0.35 if intro else 0.5)
                if i in (2, 6) and not intro:
                    _add(drm, clap if drums == "edm" else _snare(rng), tt, 0.5)
            elif drums == "lofi":
                if i in (0, 5):
                    _add(drm, kick, tt, 0.7)
                if i in (2, 6):
                    _add(drm, _snare(rng, True), tt, 0.5)
                _add(drm, hat, tt, 0.3)
            elif drums == "soft":
                _add(drm, hat, tt, 0.18 if i % 2 else 0.28)
                if i in (2, 6) and not intro:
                    _add(drm, _snare(rng, True), tt, 0.18)
            elif drums == "tension":
                _add(drm, hat, tt, 0.35)
                if i in (0, 3, 4) and not intro:
                    _add(drm, kick, tt, 0.8)
            elif drums == "clap":
                if i in (0, 4):
                    _add(drm, kick, tt, 0.6)
                if i in (2, 6):
                    _add(drm, clap, tt, 0.45)
                _add(drm, hat, tt, 0.25)
    pad = _lowpass(pad, 1800 if drums != "lofi" else 1100)
    if drums == "lofi":
        mel = _lowpass(mel, 2600)
        drm = _lowpass(drm, 5000)
        drm += (rng.random(n) < 0.0004).astype(np.float32) * rng.uniform(-0.3, 0.3, n).astype(np.float32)  # tiếng đĩa than
    mix = mel + bas + drm + pad
    mix = np.tanh(mix * 1.2)
    mix = mix[: int(total * SR)]
    return (mix / (np.max(np.abs(mix)) + 1e-6) * 0.9).astype(np.float32)


def _write_audio(samples: np.ndarray, path: Path):
    pcm = (np.clip(samples, -1, 1) * 32767).astype(np.int16).tobytes()
    p = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "s16le", "-ar", str(SR), "-ac", "1", "-i", "-",
                        "-b:a", "192k", str(path)], input=pcm, capture_output=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.decode()[-500:])


def builtin_path(tid: str) -> Path:
    p = BUILTIN_DIR / f"{tid}.mp3"
    if not p.exists():
        with _gen_lock:
            if not p.exists():
                tmp = p.with_suffix(".tmp.mp3")
                _write_audio(synth_track(tid), tmp)
                tmp.replace(p)
    return p


# ---------------- Danh sách / file ----------------
def _custom():
    out = {}
    for d in CUSTOM_DIRS:
        if d.exists():
            for f in sorted(d.iterdir()):
                if f.suffix.lower() in (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"):
                    out["custom:" + f.name] = f
    return out


def list_tracks():
    items = [{"id": k, "name": v[0], "desc": v[1], "group": "Nhạc có sẵn (miễn phí bản quyền)"} for k, v in TRACKS.items()]
    items += [{"id": k, "name": p.stem, "desc": "Nhạc bạn tải lên", "group": "Nhạc của bạn"} for k, p in _custom().items()]
    return items


def track_path(tid: str) -> Path | None:
    if not tid:
        return None
    if tid in TRACKS:
        return builtin_path(tid)
    return _custom().get(tid)


def save_custom(filename: str, data: bytes) -> str:
    name = re.sub(r"[^\w.\-]+", "_", Path(filename).name)
    if Path(name).suffix.lower() not in (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"):
        raise ValueError("Chỉ nhận file nhạc mp3, wav, m4a, aac, ogg, flac")
    p = MUSIC_DIR / "custom" / name
    p.write_bytes(data)
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                       capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        p.unlink(missing_ok=True)
        raise ValueError("File nhạc không đọc được")
    return "custom:" + name


# ---------------- Trộn vào giọng ----------------
def _decode(path: Path) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(path), "-f", "s16le", "-ac", "1", "-ar", str(SR), "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0


def _moving_avg(x, win):
    win = max(1, int(win))
    c = np.cumsum(np.insert(x, 0, 0.0))
    y = (c[win:] - c[:-win]) / win
    return np.concatenate([y, np.full(win - 1, y[-1] if len(y) else 0.0)]).astype(np.float32)


def music_bed(path: Path, n: int, volume: float, voice: np.ndarray | None = None, duck=True,
              end_sample: int | None = None) -> np.ndarray:
    """Nhạc nền dài n mẫu: lặp có crossfade, fade in/out, giảm khi có giọng."""
    src = _decode(path)
    if len(src) < SR:
        raise ValueError("Bản nhạc quá ngắn")
    xf = int(0.8 * SR)
    out = np.zeros(n, np.float32)
    pos = 0
    while pos < n:
        seg = src.copy()
        if pos > 0:
            ramp = np.linspace(0, 1, xf, dtype=np.float32)
            seg[:xf] *= ramp
            out[pos:pos + xf] *= (1 - ramp)[: max(0, min(xf, n - pos))]
        k = min(len(seg), n - pos)
        out[pos:pos + k] += seg[:k]
        pos += len(seg) - xf
    rms = np.sqrt(np.mean(src ** 2)) + 1e-6
    out *= 0.2 / rms  # chuẩn hoá độ to
    end = min(n, end_sample or n)
    fi, fo = int(0.6 * SR), int(1.5 * SR)
    out[:fi] *= np.linspace(0, 1, fi, dtype=np.float32)[: len(out[:fi])]
    if end > fo:
        out[end - fo:end] *= np.linspace(1, 0, fo, dtype=np.float32)
    out[end:] = 0
    gain = np.full(n, volume, np.float32)
    if duck and voice is not None and len(voice) and np.max(np.abs(voice)) > 0:
        env = _moving_avg(np.abs(voice[:n]), 0.05 * SR)
        env = np.clip(env / (np.percentile(env[env > 1e-4], 60) + 1e-6 if np.any(env > 1e-4) else 1), 0, 1)
        env = _moving_avg(env, 0.35 * SR)
        if len(env) < n:
            env = np.pad(env, (0, n - len(env)))
        gain *= 1 - 0.65 * np.clip(env * 1.5, 0, 1)
    return out * gain
