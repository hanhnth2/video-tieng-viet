"""Giọng nói: nhận dạng tiếng Trung -> dịch -> lồng tiếng Việt khớp thời gian."""
from __future__ import annotations

import json
import re
import threading
import wave
from pathlib import Path

import numpy as np

from . import config, voices
from .utils import has_audio, probe_duration, run

CJK = re.compile(r"[一-鿿]")
_whisper = {}
_whisper_lock = threading.Lock()


# ---------------- Nhận dạng giọng ----------------
_force_cpu = False
CUDA_ERR = ("cublas", "cudnn", "cuda", "libcu", "cannot be loaded", "no kernel image")


def _preload_cuda_libs():
    """Nạp sẵn libcublas/libcudnn từ gói pip nvidia-*-cu12 (Colab đôi khi thiếu đúng bản CUDA 12)."""
    import ctypes
    import glob
    import os
    dirs = []
    for mod in ("nvidia.cublas.lib", "nvidia.cudnn.lib", "nvidia.cuda_runtime.lib"):
        try:
            m = __import__(mod, fromlist=["_"])
            dirs += list(getattr(m, "__path__", []))
        except Exception:  # noqa: BLE001
            pass
    loaded = 0
    for d in dirs:
        for pat in ("libcudart.so.12*", "libcublasLt.so.12*", "libcublas.so.12*", "libcudnn*.so.9*"):
            for f in sorted(glob.glob(os.path.join(d, pat))):
                try:
                    ctypes.CDLL(f, mode=ctypes.RTLD_GLOBAL)
                    loaded += 1
                except OSError:
                    pass
    return loaded


def _get_whisper(size: str):
    global _force_cpu
    from faster_whisper import WhisperModel
    key = size + ("@cpu" if _force_cpu else "")
    with _whisper_lock:
        if key not in _whisper:
            if not _force_cpu:
                try:
                    n = _preload_cuda_libs()
                    if n:
                        print(f"Đã nạp {n} thư viện CUDA 12 từ pip")
                    import ctranslate2
                    if ctranslate2.get_cuda_device_count() > 0:
                        _whisper[key] = WhisperModel(size, device="cuda", compute_type="float16")
                    else:
                        _force_cpu = True
                except Exception as e:  # noqa: BLE001
                    print("Whisper GPU lỗi, chuyển CPU:", str(e)[:150])
                    _force_cpu = True
            if _force_cpu:
                key = size + "@cpu"
                if key not in _whisper:
                    import os
                    _whisper[key] = WhisperModel(size, device="cpu", compute_type="int8",
                                                 cpu_threads=os.cpu_count() or 4)
        return _whisper[key]


def _load_wav(p):
    with wave.open(str(p), "rb") as w:
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def _run_transcribe(model, audio):
    with _whisper_lock:  # 1 model dùng chung, tránh chạy song song trên cùng GPU
        segs, _ = model.transcribe(audio, language="zh", vad_filter=True,
                                   initial_prompt="以下是普通话的句子。")
        return list(segs)   # lỗi thiếu thư viện CUDA thường chỉ xuất hiện ở bước này


def transcribe(wav: Path, size: str, log=print):
    global _force_cpu
    audio = _load_wav(wav)
    try:
        segs = _run_transcribe(_get_whisper(size), audio)
    except Exception as e:  # noqa: BLE001
        if _force_cpu or not any(k in str(e).lower() for k in CUDA_ERR):
            raise
        log(f"  GPU lỗi ({str(e)[:90]}), chuyển sang CPU – sẽ chậm hơn")
        _force_cpu = True
        segs = _run_transcribe(_get_whisper(size), audio)
    return [(s.start, s.end, s.text.strip()) for s in segs if s.text.strip()]


# ---------------- Dịch ----------------
_cache_lock = threading.Lock()
_CACHE_FILE = config.CACHE_DIR / "translations.json"


def _load_cache():
    try:
        return json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save_cache(c):
    with _cache_lock:
        _CACHE_FILE.write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")


def translate_google(texts):
    from deep_translator import GoogleTranslator, MyMemoryTranslator
    engines = [GoogleTranslator(source="zh-CN", target="vi")]
    try:
        engines.append(MyMemoryTranslator(source="zh-CN", target="vi-VN"))
    except Exception:  # noqa: BLE001
        pass
    out = []
    for t in texts:
        res, err = None, None
        for eng in engines:
            try:
                r = eng.translate(t)
                if r and r.strip() and (r.strip() != t.strip() or not CJK.search(t)):
                    res = r.strip()
                    break
            except Exception as e:  # noqa: BLE001
                err = e
        if res is None:
            raise RuntimeError(f"Không dịch được: {t!r} ({err})")
        out.append(res)
    return out


def translate_claude(texts, context=""):
    import anthropic
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    prompt = (
        "Bạn là biên dịch viên video mạng xã hội. Dịch các đoạn tiếng Trung sau sang tiếng Việt "
        "tự nhiên, ngắn gọn, giọng văn mạng xã hội/bán hàng, giữ đúng nghĩa và mạch nội dung. "
        "Câu dịch nên có độ dài gần với câu gốc để lồng tiếng kịp thời gian. "
        f"{context}\n"
        "Chỉ trả về một mảng JSON các chuỗi, đúng số lượng và thứ tự như đầu vào.\n\n"
        + json.dumps(texts, ensure_ascii=False)
    )
    msg = client.beta.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=16000,
        output_config={"effort": "low"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{"role": "user", "content": prompt}],
    )
    if msg.stop_reason == "refusal":
        raise RuntimeError("Claude từ chối yêu cầu")
    raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
    m = re.search(r"\[.*\]", raw, re.S)
    res = json.loads(m.group(0) if m else raw)
    if not isinstance(res, list) or len(res) != len(texts):
        raise ValueError("Số câu dịch không khớp")
    return [str(x).strip() for x in res]


def translate(texts, engine="auto", context=""):
    if not texts:
        return []
    cache = _load_cache()
    use_claude = engine == "claude" or (engine == "auto" and config.ANTHROPIC_API_KEY)
    tag = "c:" if use_claude else "g:"
    todo = [t for t in dict.fromkeys(texts) if tag + t not in cache]
    if todo:
        res = None
        if use_claude and config.ANTHROPIC_API_KEY:
            try:
                res = translate_claude(todo, context)
            except Exception as e:  # noqa: BLE001
                print("Claude lỗi, dùng Google Translate:", str(e)[:150])
                tag = "g:"
                todo = [t for t in dict.fromkeys(texts) if tag + t not in cache]
        if res is None:
            res = translate_google(todo)
        for zh, vi in zip(todo, res):
            cache[tag + zh] = vi
        _save_cache(cache)
    out = [cache.get(tag + t) or cache.get("c:" + t) or cache.get("g:" + t) for t in texts]
    bad = [t for t, v in zip(texts, out) if not v or CJK.search(v)]
    if bad:
        raise RuntimeError(f"Còn {len(bad)} câu chưa dịch được, ví dụ: {bad[0]!r}")
    return out


# ---------------- Tách nhạc nền ----------------
def separate_background(src_wav: Path, work: Path) -> Path | None:
    """Dùng demucs (nếu có cài) để lấy phần nhạc nền không có giọng nói."""
    try:
        import demucs  # noqa: F401
    except ImportError:
        return None
    out = work / "demucs"
    try:
        run(["python", "-m", "demucs", "--two-stems=vocals", "-n", "htdemucs", "-o", out, src_wav], timeout=3600)
    except Exception as e:  # noqa: BLE001
        print("demucs lỗi:", str(e)[:200])
        return None
    cands = list(out.glob("**/no_vocals.wav"))
    return cands[0] if cands else None


# ---------------- Lồng tiếng ----------------
def build_dub(segs, vi, opts, work: Path, src_video: Path, total: float, log=print):
    """Trả về (đường dẫn dub.wav, danh sách cue phụ đề)."""
    sr = 44100
    dub = np.zeros(int((total + 1.0) * sr), dtype=np.float32)
    cues = []
    for i, (st, en, _) in enumerate(segs):
        nxt = segs[i + 1][0] if i + 1 < len(segs) else total
        allowed = max(0.3, max(en - st, nxt - st - 0.05))
        mp3 = voices.synth(vi[i], opts.voice, work / f"tts_{i:04d}.mp3", speed=opts.speed)
        dur = probe_duration(mp3)
        filt = []
        if dur > allowed:
            factor = min(dur / allowed, opts.max_speedup)
            filt.append(f"atempo={factor:.3f}")
            dur /= factor
        wav = work / f"tts_{i:04d}.wav"
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", mp3, "-ac", "1", "-ar", str(sr)]
        if filt:
            cmd += ["-filter:a", ",".join(filt)]
        run(cmd + [wav])
        a = _load_wav(wav)
        p = int(st * sr)
        if p >= len(dub):
            continue
        a = a[: len(dub) - p]
        dub[p:p + len(a)] += a
        cues.append((st, min(max(en, st + dur), nxt), vi[i]))
        if (i + 1) % 5 == 0:
            log(f"  đã tạo giọng {i + 1}/{len(segs)} câu")

    voice_only = dub.copy()
    if opts.bg_volume > 0 and has_audio(src_video):
        full = work / "orig_44k.wav"
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", src_video, "-vn", "-ac", "1", "-ar", str(sr), full])
        bg_src = separate_background(full, work) if opts.separate_vocals else None
        if bg_src:
            log("  đã tách nhạc nền khỏi giọng gốc (demucs)")
            mono = work / "bg_mono.wav"
            run(["ffmpeg", "-y", "-loglevel", "error", "-i", bg_src, "-ac", "1", "-ar", str(sr), mono])
            bg_src = mono
        else:
            bg_src = full
        bg = _load_wav(bg_src)[: len(dub)]
        dub[: len(bg)] += bg * opts.bg_volume

    if opts.music:
        from . import music
        mp = music.track_path(opts.music)
        if mp and mp.exists():
            dub += music.music_bed(mp, len(dub), opts.music_volume, voice_only, opts.music_duck,
                                   end_sample=int(total * sr))
            log(f"  đã chèn nhạc nền: {mp.stem}")
        else:
            log("  không tìm thấy bản nhạc đã chọn, bỏ qua")

    peak = float(np.max(np.abs(dub))) if len(dub) else 0
    if peak > 0.98:
        dub *= 0.98 / peak
    out = work / "dub.wav"
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((dub * 32767).astype(np.int16).tobytes())
    if getattr(opts, "loudnorm", True) and peak > 0.001:
        # lọc tiếng ù, chuẩn độ to -14 LUFS (mức TikTok/Reels/YouTube khuyến nghị), stereo 48 kHz
        norm = work / "dub_norm.wav"
        try:
            run(["ffmpeg", "-y", "-loglevel", "error", "-i", out, "-af",
                 "highpass=f=70,loudnorm=I=-14:TP=-1.5:LRA=11", "-ar", "48000", "-ac", "2", norm])
            log("  đã chuẩn hoá âm thanh -14 LUFS")
            return norm, cues
        except Exception as e:  # noqa: BLE001
            log(f"  bỏ qua chuẩn hoá âm thanh: {str(e)[:80]}")
    return out, cues


def extract_wav16k(src: Path, dst: Path):
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-vn", "-ac", "1", "-ar", "16000", dst])
    return dst
