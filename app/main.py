"""Web server: uvicorn app.main:app --host 0.0.0.0 --port 8000"""
from __future__ import annotations

import json
import re
import shutil
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import auth, captions, config, hookvideo, music, settings, signature, textstyle, voices
from .config import JobOptions
from .downloader import DownloadError, extract_url
from .jobs import JobManager

app = FastAPI(title="Video chuyển đổi Tiếng Việt")
app.middleware("http")(auth.middleware)


@app.get("/login")
def login_form(next: str = "/"):
    if not auth.password():
        return RedirectResponse("/", status_code=303)
    return auth.login_page(next if next.startswith("/") else "/")


@app.post("/login")
def login_submit(request: Request, password: str = Form(""), next: str = Form("/")):
    import hmac as _h
    if not _h.compare_digest(password.strip(), auth.password()):
        return auth.login_page(next, error=True)
    return auth.set_cookie(RedirectResponse(next if next.startswith("/") else "/", status_code=303), request)
manager = JobManager()
STATIC = Path(__file__).resolve().parent / "static"
SAFE_NAME = re.compile(r"^[\w.\-]+$")

PUBLIC_FIELDS = ("id", "status", "input", "title", "progress", "step", "step_label", "created", "duration",
                 "error", "result", "srt", "debug_images", "transcript", "screen_texts", "options", "captions", "hook_result", "hook_text", "review",
                 "video_source")


def _public(job, logs=True):
    d = {k: job.data.get(k) for k in PUBLIC_FIELDS}
    if logs:
        d["logs"] = job.data.get("logs", [])[-80:]
    return d


@app.get("/api/config")
def get_config():
    return {"whisper_model": config.WHISPER_MODEL, "claude": bool(config.ANTHROPIC_API_KEY), "gemini": bool(config.GEMINI_API_KEY),
            "fpt": bool(config.FPT_API_KEY), "defaults": JobOptions().to_dict()}


@app.get("/api/voices")
def get_voices():
    return voices.list_voices()


@app.get("/api/voices/preview")
def voice_preview(voice: str):
    if voice not in {v["id"] for v in voices.list_voices()}:
        raise HTTPException(404, "Không có giọng này")
    return FileResponse(voices.preview(voice), media_type="audio/mpeg")


@app.get("/api/text/presets")
def text_presets():
    return textstyle.list_presets()


@app.get("/api/text/fonts")
def text_fonts():
    return textstyle.list_fonts()


@app.post("/api/text/fonts")
async def upload_font(file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > 20_000_000:
        raise HTTPException(400, "File font quá lớn")
    try:
        fid = textstyle.save_custom_font(file.filename or "font.ttf", data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"id": fid}


@app.get("/api/text/preview")
def text_preview(preset: str = "", text_preset: str = "", font: str = "bevietnam", text: str = "Chữ Việt",
                 text_color: str = "", bg_color: str = "", stroke_color: str = "", bg_opacity: float = -1,
                 size: int = 64, bg_mode: str = "preset", fit_mode: str = ""):
    preset = preset or text_preset or "yellow_box"
    if preset not in textstyle.PRESETS:
        raise HTTPException(404, "Không có kiểu chữ này")
    color = re.compile(r"^(#[0-9a-fA-F]{6})?$")
    if not all(color.match(c) for c in (text_color, bg_color, stroke_color)):
        raise HTTPException(400, "Mã màu không hợp lệ")
    p = textstyle.preview_png(text[:80] or "Chữ Việt", preset, font, text_color, bg_color, stroke_color,
                              bg_opacity, size=max(16, min(96, size)),
                              bg_mode=bg_mode if bg_mode in ("preset", "none", "color") else "preset",
                              compact=fit_mode == "fit")
    return FileResponse(p, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/api/settings")
def get_settings():
    return settings.cookie_status()


@app.post("/api/settings/xhs_cookie")
def set_xhs_cookie(cookie: str = Form("")):
    c = settings.parse_cookie(cookie)
    if cookie.strip() and not c:
        raise HTTPException(400, "Không đọc được cookie. Hãy dán chuỗi cookie hoặc file xuất từ tiện ích Cookie-Editor.")
    settings.save(xhs_cookie=c)
    return settings.cookie_status()


@app.get("/api/signature/options")
def signature_options():
    return {"effects": signature.EFFECTS, "positions": signature.POSITIONS}


@app.get("/api/music")
def music_list():
    return music.list_tracks()


@app.get("/api/music/preview")
def music_preview(id: str):
    if id not in {t["id"] for t in music.list_tracks()}:
        raise HTTPException(404, "Không có bản nhạc này")
    p = music.track_path(id)
    return FileResponse(p, media_type="audio/mpeg" if p.suffix == ".mp3" else None)


@app.post("/api/music")
async def music_upload(file: UploadFile = File(...), confirm: str = Form("")):
    if confirm != "1":
        raise HTTPException(400, "Hãy xác nhận bạn có quyền sử dụng bản nhạc này cho mục đích thương mại.")
    data = await file.read()
    if len(data) > 50_000_000:
        raise HTTPException(400, "File nhạc quá lớn (tối đa 50MB)")
    try:
        return {"id": music.save_custom(file.filename or "music.mp3", data)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/jobs/{jid}/review")
async def submit_review(jid: str, request: Request):
    j = manager.get(jid)
    if not j or j.data.get("status") != "review":
        raise HTTPException(400, "Video không ở bước duyệt chữ")
    body = await request.json()
    j.submit_review({"selected": body.get("selected", []), "edits": body.get("edits", {})})
    return {"ok": True}


@app.post("/api/jobs/{jid}/captions")
def make_captions(jid: str, tone: str = Form(""), trending: str = Form(""), niche: str = Form(""),
                  affiliate: str = Form("no"), credit: str = Form("")):
    j = manager.get(jid)
    if not j:
        raise HTTPException(404, "Không tìm thấy job")
    if j.data.get("status") != "done":
        raise HTTPException(400, "Video chưa xử lý xong")
    data = captions.generate(j.data, tone=tone[:300], trending=trending[:300], niche=niche[:200],
                             affiliate=affiliate == "yes", credit=credit[:120])
    j.update(captions=data)
    return data


@app.post("/api/jobs/{jid}/hook")
def burn_hook(jid: str, text: str = Form(...), preset: str = Form("yellow_box"), font: str = Form("bevietnam"),
              seconds: float = Form(3.0), position: str = Form("center")):
    j = manager.get(jid)
    if not j or j.data.get("status") != "done":
        raise HTTPException(400, "Video chưa xử lý xong")
    text = captions.soften(text.strip())[:120]
    if not text:
        raise HTTPException(400, "Chưa có nội dung hook")
    if captions.check_compliance(text, "block"):
        raise HTTPException(400, "Câu hook có từ ngữ dễ vi phạm: " + "; ".join(captions.check_compliance(text, "block")))
    if preset not in textstyle.PRESETS or preset == "original":
        preset = "yellow_box"
    out = j.dir / "result_hook.mp4"
    try:
        hookvideo.burn(j.dir / j.data.get("result", "result.mp4"), out, text, preset, font, seconds, position)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"Không chèn được hook: {str(e)[:300]}")
    j.update(hook_result=out.name, hook_text=text)
    return {"file": out.name, "text": text}


@app.post("/api/jobs")
async def create_job(link: str = Form(""), options: str = Form("{}"), file: UploadFile | None = File(None)):
    try:
        opts = JobOptions.from_dict(json.loads(options or "{}"))
    except json.JSONDecodeError:
        raise HTTPException(400, "Tuỳ chọn không hợp lệ")
    if file is not None and file.filename:
        tmp = Path(tempfile.mkstemp(suffix=".mp4", dir=config.DATA_DIR)[1])
        with open(tmp, "wb") as f:
            shutil.copyfileobj(file.file, f)
        job = manager.create(link or file.filename, opts, uploaded=tmp)
    else:
        try:
            extract_url(link)
        except DownloadError as e:
            raise HTTPException(400, str(e))
        job = manager.create(link, opts)
    return _public(job)


@app.get("/api/jobs")
def list_jobs():
    return [_public(j, logs=False) for j in manager.list()]


@app.get("/api/jobs/{jid}")
def get_job(jid: str):
    j = manager.get(jid)
    if not j:
        raise HTTPException(404, "Không tìm thấy job")
    return _public(j)


@app.delete("/api/jobs/{jid}")
def delete_job(jid: str):
    if not manager.delete(jid):
        raise HTTPException(400, "Không xoá được (job đang chạy hoặc không tồn tại)")
    return {"ok": True}


@app.get("/api/jobs/{jid}/files/{name:path}")
def job_file(jid: str, name: str, download: bool = False):
    j = manager.get(jid)
    if not j or not re.fullmatch(r"(crops/)?[\w.\-]+", name) or ".." in name:
        raise HTTPException(404)
    p = j.dir / name
    if not p.is_file() or name == "job.json":
        raise HTTPException(404)
    fname = None
    if download:
        stem = re.sub(r"[^\w\-]+", "_", (j.data.get("title") or jid))[:60]
        fname = f"{stem}_vi{p.suffix}"
    return FileResponse(p, filename=fname)


@app.get("/api/health")
def health():
    return JSONResponse({"ok": True})


app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
