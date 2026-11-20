"""Chạy toàn bộ quy trình cho 1 job."""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from . import config, onscreen, signature, speech
from .config import JobOptions
from .downloader import download
from .utils import AUDIO_ARGS, has_audio, probe_duration, run, video_encode_args, write_srt

STYLE_KEYS = {"text_preset", "bg_mode", "bg_color", "text_color", "stroke_color", "bg_opacity", "font"}


def track_opts(opts: JobOptions, override: dict | None) -> JobOptions:
    """Tuỳ chọn riêng cho 1 đoạn chữ (màu nền, màu chữ, kiểu chữ...), các tuỳ chọn khác lấy theo cài đặt chung."""
    if not override:
        return opts
    d = opts.to_dict()
    d.update({k: v for k, v in override.items() if k in STYLE_KEYS and v is not None})
    return JobOptions.from_dict(d)


# (tên bước, % bắt đầu, % kết thúc)
STEPS = {
    "download": ("Tải video", 0, 8),
    "analyze": ("Dò chữ & logo trên hình", 8, 35),
    "asr": ("Nhận dạng giọng Trung", 35, 50),
    "translate": ("Dịch sang tiếng Việt", 50, 56),
    "tts": ("Lồng giọng Việt", 56, 70),
    "render": ("Xoá chữ/logo, vẽ chữ Việt, xuất video", 70, 98),
    "finish": ("Hoàn tất", 98, 100),
}


def process(job, opts: JobOptions):
    work: Path = job.dir / "work"
    work.mkdir(parents=True, exist_ok=True)

    clock = {"t": time.time(), "name": None}

    def step(name):
        label, a, _ = STEPS[name]
        if clock["name"]:
            job.log(f"  ⏱ {STEPS[clock['name']][0]}: {time.time() - clock['t']:.0f} giây")
        clock.update(t=time.time(), name=name)
        job.update(step=name, step_label=label, progress=a)
        job.log(f"▶ {label}")

    def sub(name):
        _, a, b = STEPS[name]

        def _log(msg, progress=None):
            job.log(msg)
            if progress is not None:
                job.update(progress=round(a + (b - a) * min(1.0, progress), 1))
        return _log

    # ---------- 1. Video nguồn ----------
    src = job.dir / "source.mp4"
    if not src.exists():
        step("download")
        meta = download(job.data["input"], src, log=sub("download"))
        job.update(title=meta.get("title", ""), video_source=meta.get("source", ""))
        if meta.get("source") == "origin":
            job.log("  đã lấy được bản gốc trên CDN (thường không có watermark)")
    total = probe_duration(src)
    job.update(duration=round(total, 2))

    # ---------- 2. Dò chữ / logo ----------
    step("analyze")
    info = onscreen.analyze(src, opts, log=sub("analyze"))
    end_t = info["trim_at"] or total
    # chỉ dịch tiêu đề / phụ đề (chữ chèn lên video); bỏ qua chữ in trên thiết bị, dụng cụ, bao bì
    n_scene = 0
    for tr in info["tracks"]:
        if tr["wm"]:
            continue
        tr["skip"] = (not opts.replace_text) or (opts.text_scope == "overlay" and tr.get("kind") == "scene")
        n_scene += tr.get("kind") == "scene"
    if opts.replace_text and n_scene:
        job.log(f"  {n_scene} đoạn chữ nằm trên đồ vật/cảnh quay"
                + (" → giữ nguyên, không dịch" if opts.text_scope == "overlay" else " → vẫn dịch (chế độ dịch tất cả)"))
    if opts.replace_text or opts.remove_logo:
        job.update(debug_images=onscreen.save_debug(src, info, job.dir))

    # ---------- 3. Giọng nói ----------
    cues = []
    dub_wav = None
    if has_audio(src):
        step("asr")
        wav16 = speech.extract_wav16k(src, work / "orig16k.wav")
        segs = speech.transcribe(wav16, config.WHISPER_MODEL, log=sub("asr"))
        segs = [(s, min(e, end_t), t) for s, e, t in segs if s < end_t - 0.2]
        job.log(f"  {len(segs)} câu thoại")
    else:
        segs = []
        job.log("  video không có âm thanh")

    step("translate")
    cand = [t for t in info["tracks"] if not t["wm"] and not t.get("absorbed")] if opts.replace_text else []
    review = opts.review_text and bool(cand)
    # khi duyệt: dịch cả chữ bị loại để bạn xem và chọn lại
    text_tracks = cand if review else [t for t in cand if not t.get("skip")]
    screen_texts = list(dict.fromkeys(t["text"] for t in text_tracks))
    all_zh = [s[2] for s in segs] + screen_texts
    all_vi = speech.translate(all_zh, opts.translator) if all_zh else []
    vi_speech = all_vi[:len(segs)]
    vi_map = dict(zip(screen_texts, all_vi[len(segs):]))
    for zh, vi in list(zip(all_zh, all_vi))[:8]:
        job.log(f"  {zh}  →  {vi}")
    for tr in text_tracks:
        tr["vi"] = vi_map[tr["text"]]

    # ---------- duyệt chữ trên hình (tuỳ chọn) ----------
    if review:
        items = []
        crops = onscreen.save_crops(src, cand, job.dir / "crops")
        for i, tr in enumerate(cand):
            items.append({"id": i, "zh": tr["text"], "vi": tr["vi"], "kind": tr.get("kind"), "score": tr.get("score"),
                          "why": tr.get("why", []), "checked": not tr.get("skip"), "crop": crops.get(i),
                          "t0": round(tr["t0"], 1), "t1": round(tr["t1"], 1)})
        job.begin_review()
        job.update(status="review", review=items, step_label="Chờ bạn duyệt chữ trên hình")
        job.log("⏸ Chờ bạn duyệt chữ trên hình (bỏ chọn chữ không muốn dịch, sửa bản dịch nếu cần)…")
        decision = job.wait_review(timeout=3 * 3600)
        job.update(status="running", review=None)
        if decision is None:
            job.log("  hết thời gian chờ duyệt → dùng lựa chọn tự động")
            decision = {"selected": [it["id"] for it in items if it["checked"]], "edits": {}}
        sel = {int(x) for x in decision.get("selected", [])}
        styles = {int(k): v for k, v in (decision.get("styles") or {}).items() if isinstance(v, dict)}
        edits = {int(k): str(v).strip() for k, v in (decision.get("edits") or {}).items() if str(v).strip()}
        for i, tr in enumerate(cand):
            tr["skip"] = i not in sel
            if i in edits:
                tr["vi"] = edits[i][:300]
            if i in styles:
                tr["style_override"] = styles[i]   # kiểu chữ / màu riêng cho đoạn này
        job.log(f"  đã duyệt: dịch {len(sel)}/{len(cand)} đoạn chữ")
        if opts.replace_text or opts.remove_logo:
            job.update(debug_images=onscreen.save_debug(src, info, job.dir))
        text_tracks = [t for t in cand if not t.get("skip")]

    job.update(transcript=[{"start": round(s[0], 2), "end": round(s[1], 2), "zh": s[2], "vi": v}
                           for s, v in zip(segs, vi_speech)],
               screen_texts=[{"zh": t["text"], "vi": t["vi"]} for t in text_tracks])

    step("tts")
    dub_wav, cues = speech.build_dub(segs, vi_speech, opts, work, src, end_t, log=sub("tts"))
    srt = job.dir / "result.srt"
    write_srt(srt, cues)
    shutil.copy(srt, work / "subs.srt")

    # ---------- 4. Xuất video ----------
    step("render")
    short = min(info["W"], info["H"])
    if opts.upscale and 0 < short < 1080:
        onscreen.scale_info(info, min(2.5, 1080 / short))
        job.log(f"  nâng độ phân giải: {info['srcW']}x{info['srcH']} → {info['W']}x{info['H']}")
    # lưu lại để "chỉnh từng dòng chữ & xuất lại" mà không phải xử lý lại từ đầu
    if not (job.dir / "crops").exists() and cand:
        onscreen.save_crops(src, cand, job.dir / "crops")
    shutil.copy(dub_wav, job.dir / "dub.wav")
    save_state(job, info, cand, end_t)
    render_output(job, info, opts, src, job.dir / "dub.wav", end_t, work, sub("render"))

    step("finish")
    shutil.rmtree(work, ignore_errors=True)
    job.update(progress=100, result="result.mp4", srt="result.srt", screen_items=screen_items(job, cand))


def render_output(job, info, opts, src, dub_wav, end_t, work, log):
    """Vẽ chữ Việt + chữ ký lên video và xuất file result.mp4 (dùng cho cả lần đầu và khi xuất lại)."""
    text_tracks = [t for t in info["tracks"] if not t["wm"] and not t.get("absorbed") and not t.get("skip")]
    for tr in text_tracks:
        tr["sprite"] = onscreen.make_sprite(tr["vi"], tr, info["W"], track_opts(opts, tr.get("style_override")))
    out = job.dir / "result.mp4"
    tmp_out = job.dir / "result.tmp.mp4"
    stage = work / "stage.mp4" if opts.burn_subs else tmp_out
    sig = signature.build(opts, info["W"], info["H"])
    if sig:
        job.log(f"  chèn chữ ký: {opts.wm_text} ({signature.EFFECTS[sig.effect]})")
    if info["tracks"] or info["regions"] or sig or info.get("scale", 1.0) != 1.0:
        onscreen.render(src, dub_wav, info, opts, stage, log=log, signature=sig)
    else:
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-i", dub_wav, "-map", "0:v:0", "-map", "1:a:0",
             "-t", f"{end_t:.3f}", *video_encode_args(opts.quality, info.get("color", "bt709")), *AUDIO_ARGS,
             "-shortest", stage])
    if opts.burn_subs:
        shutil.copy(job.dir / "result.srt", work / "subs.srt")
        style = ("FontName=Noto Sans,FontSize=16,PrimaryColour=&H00FFFFFF,BackColour=&H99000000,"
                 "BorderStyle=3,Outline=1,Alignment=2,MarginV=24")
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", stage.name, "-vf",
             f"subtitles=subs.srt:force_style='{style}'", *video_encode_args(opts.quality, info.get("color", "bt709")),
             "-c:a", "copy", tmp_out.resolve()], cwd=work)
    tmp_out.replace(out)
    job.update(result_size=out.stat().st_size)
    for tr in text_tracks:
        tr.pop("sprite", None)
    for tr in info["tracks"]:
        tr.pop("_cache", None)


# ---------------- lưu / chỉnh lại sau khi xuất ----------------
def save_state(job, info, cand, end_t):
    import pickle
    clean = dict(info)
    clean["tracks"] = [{k: v for k, v in tr.items() if k not in ("sprite", "_cache")} for tr in info["tracks"]]
    ids = [info["tracks"].index(t) for t in cand]
    with open(job.dir / "render_state.pkl", "wb") as f:
        pickle.dump({"info": clean, "cand": ids, "end_t": end_t}, f)


def screen_items(job, cand):
    items = []
    for i, tr in enumerate(cand):
        crop = f"crops/c{i}.jpg"
        items.append({"id": i, "zh": tr["text"], "vi": tr.get("vi", ""), "kind": tr.get("kind"),
                      "checked": not tr.get("skip"), "style": tr.get("style_override") or {},
                      "crop": crop if (job.dir / crop).exists() else None,
                      "t0": round(tr["t0"], 1), "t1": round(tr["t1"], 1)})
    return items


def rerender(job, decision: dict):
    """Chỉnh từng dòng chữ (bản dịch, phông, nền, màu) rồi xuất lại – dùng lại kết quả dò chữ, dịch, lồng tiếng."""
    import pickle
    from . import speech
    t0 = time.time()
    with open(job.dir / "render_state.pkl", "rb") as f:
        st = pickle.load(f)
    info = st["info"]
    cand = [info["tracks"][i] for i in st["cand"]]
    opts = JobOptions.from_dict(job.data.get("options") or {})
    sel = {int(x) for x in decision.get("selected", [])}
    edits = {int(k): str(v).strip() for k, v in (decision.get("edits") or {}).items() if str(v).strip()}
    styles = {int(k): v for k, v in (decision.get("styles") or {}).items() if isinstance(v, dict)}
    need_tr = [tr for i, tr in enumerate(cand) if i in sel and not tr.get("vi") and i not in edits]
    if need_tr:   # dòng trước đây không dịch (chữ trên đồ vật) nay được chọn -> dịch thêm
        vis = speech.translate([t["text"] for t in need_tr], opts.translator)
        for tr, v in zip(need_tr, vis):
            tr["vi"] = v
    for i, tr in enumerate(cand):
        tr["skip"] = i not in sel
        if i in edits:
            tr["vi"] = edits[i][:300]
        if i in styles:
            tr["style_override"] = styles[i]
    job.update(status="running", step="render", step_label="Xuất lại video với chữ đã chỉnh", progress=70,
               hook_result=None)
    job.log("▶ Xuất lại video với chữ đã chỉnh")
    work = job.dir / "work_rerender"
    work.mkdir(exist_ok=True)
    try:
        def _log(msg, progress=None):
            job.log(msg)
            if progress is not None:
                job.update(progress=round(70 + 28 * min(1.0, progress), 1))
        render_output(job, info, opts, job.dir / "source.mp4", job.dir / "dub.wav", st["end_t"], work, _log)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    with open(job.dir / "render_state.pkl", "wb") as f:
        pickle.dump(st, f)
    job.log(f"  ⏱ Xuất lại: {time.time() - t0:.0f} giây")
    job.update(progress=100, screen_items=screen_items(job, cand),
               screen_texts=[{"zh": t["text"], "vi": t["vi"]} for t in cand if not t.get("skip")])
