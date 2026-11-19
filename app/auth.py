"""Bảo vệ trang web bằng mật khẩu (bật khi đặt biến môi trường APP_PASSWORD).

Dùng khi chạy trên máy chủ công khai (Hugging Face Spaces / VPS) để người khác có link cũng không dùng được.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

COOKIE = "vv_auth"
OPEN_PATHS = ("/login", "/api/health")


def password() -> str:
    return os.environ.get("APP_PASSWORD", "").strip()


def token(pw: str) -> str:
    return hmac.new(pw.encode(), b"video-tieng-viet", hashlib.sha256).hexdigest()


def is_ok(request: Request) -> bool:
    pw = password()
    if not pw:
        return True
    return hmac.compare_digest(request.cookies.get(COOKIE, ""), token(pw))


LOGIN_HTML = """<!doctype html><html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Đăng nhập</title>
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0f1115;color:#e8eaf0;
font:15px/1.5 system-ui,-apple-system,Roboto,sans-serif;padding:16px}
.box{width:100%;max-width:360px;background:#171a21;border:1px solid #2a2f3a;border-radius:16px;padding:22px}
.logo{width:56px;height:56px;border-radius:16px;background:linear-gradient(135deg,#ff2e4d,#ff7a45);display:grid;
place-items:center;font-weight:800;margin:0 auto 10px}h1{font-size:18px;text-align:center;margin:0}
.by{text-align:center;color:#8b93a7;font-size:13px}.by b{color:#f4c710}
input{width:100%;box-sizing:border-box;margin-top:16px;background:#1e222b;border:1px solid #2a2f3a;color:#e8eaf0;
border-radius:10px;padding:12px;font:inherit}button{width:100%;margin-top:12px;background:#ff2e4d;border:0;color:#fff;
border-radius:10px;padding:12px;font:inherit;font-weight:700}.err{color:#fca5a5;font-size:13px;margin-top:10px;text-align:center}
</style></head><body><form class="box" method="post" action="/login">
<div class="logo">中→V</div><h1>Video chuyển đổi Tiếng Việt</h1><div class="by">Được tạo bởi <b>Ngô Thị Hồng Hạnh</b></div>
<input type="hidden" name="next" value="__NEXT__">
<input type="password" name="password" placeholder="Nhập mật khẩu" autofocus required>
<button type="submit">Vào</button>__ERR__</form></body></html>"""


def login_page(next_url="/", error=False):
    html = LOGIN_HTML.replace("__NEXT__", next_url.replace('"', "")).replace(
        "__ERR__", '<div class="err">Sai mật khẩu</div>' if error else "")
    return HTMLResponse(html, status_code=401 if error else 200)


async def middleware(request: Request, call_next):
    path = request.url.path
    if not password() or path.startswith(OPEN_PATHS) or is_ok(request):
        return await call_next(request)
    if path.startswith("/api/"):
        return JSONResponse({"detail": "Cần đăng nhập. Tải lại trang để nhập mật khẩu."}, status_code=401)
    nxt = path + (("?" + request.url.query) if request.url.query else "")
    return RedirectResponse("/login?next=" + quote(nxt), status_code=303)


def set_cookie(resp, request: Request):
    https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    resp.set_cookie(COOKIE, token(password()), max_age=365 * 86400, httponly=True,
                    secure=https, samesite="none" if https else "lax")
    return resp
