"""Cài đặt lưu trên máy chủ (vd cookie Xiaohongshu) — chỉnh được ngay trên giao diện web."""
from __future__ import annotations

import json
import re
import threading

from .config import DATA_DIR, XHS_COOKIE

_FILE = DATA_DIR / "settings.json"
_lock = threading.Lock()


def load() -> dict:
    try:
        return json.loads(_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def save(**kw):
    with _lock:
        d = load()
        d.update(kw)
        _FILE.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


def parse_cookie(text: str) -> str:
    """Nhận cookie ở nhiều dạng -> chuỗi 'a=1; b=2'.

    - Chuỗi header:            a=1; b=2
    - Netscape cookies.txt:    domain \\t flag \\t path \\t secure \\t expiry \\t name \\t value
    - JSON (tiện ích trình duyệt): [{"name": "...", "value": "...", "domain": "..."}]
    """
    t = (text or "").strip()
    if not t:
        return ""
    if t.lower().startswith("cookie:"):
        t = t[7:].strip()
    if t.startswith("[") or t.startswith("{"):
        try:
            data = json.loads(t)
            if isinstance(data, dict):
                data = data.get("cookies") or [data]
            pairs = [f"{c['name']}={c['value']}" for c in data
                     if isinstance(c, dict) and "name" in c and "value" in c
                     and any(h in str(c.get("domain", "xiaohongshu")) for h in ("xiaohongshu", "rednote", "xhscdn"))]
            return "; ".join(pairs)
        except Exception:  # noqa: BLE001
            pass
    if "\t" in t:
        pairs = []
        for line in t.splitlines():
            parts = line.split("\t")
            if len(parts) >= 7 and not line.startswith("#") or line.startswith("#HttpOnly_"):
                parts = line.replace("#HttpOnly_", "").split("\t")
                if len(parts) >= 7 and any(h in parts[0] for h in ("xiaohongshu", "rednote", "xhscdn")):
                    pairs.append(f"{parts[5]}={parts[6].strip()}")
        return "; ".join(pairs)
    return re.sub(r"\s*\n\s*", " ", t)


def xhs_cookie() -> str:
    return load().get("xhs_cookie") or XHS_COOKIE


def cookie_status() -> dict:
    c = xhs_cookie()
    names = [p.split("=", 1)[0].strip() for p in c.split(";") if "=" in p]
    return {"has_cookie": bool(c), "count": len(names), "logged_in": "web_session" in names}
