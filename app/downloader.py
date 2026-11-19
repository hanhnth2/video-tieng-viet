"""Tải video từ link Xiaohongshu (xhslink.com / xiaohongshu.com).

Thứ tự thử:
1. Đọc trang note, lấy JSON window.__INITIAL_STATE__ -> link video gốc
   (originVideoKey trên CDN thường KHÔNG có watermark).
2. yt-dlp (có sẵn extractor XiaoHongShu).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urlparse

import httpx

from . import settings

UA_DESKTOP = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
UA_MOBILE = ("Mozilla/5.0 (Linux; Android 14; 23124RA7EO) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36")
NOTE_RE = re.compile(r"/(?:explore|discovery/item|notes?)/([0-9a-fA-F]{24})")
URL_RE = re.compile(r"https?://[^\s，,。]+")
XHS_HOSTS = ("xhslink.com", "xiaohongshu.com", "xhscdn.com", "rednote.com", "xhslink.cn")


class DownloadError(RuntimeError):
    pass


def extract_url(text: str) -> str:
    """Người dùng hay dán cả đoạn chia sẻ ('... http://xhslink.com/o/xxx 复制本条信息...')."""
    m = URL_RE.search(text or "")
    if not m:
        raise DownloadError("Không tìm thấy đường link trong nội dung đã nhập.")
    url = m.group(0).rstrip(").]}>'\"")
    host = urlparse(url).netloc.lower()
    if not any(host == h or host.endswith("." + h) for h in XHS_HOSTS):
        raise DownloadError("Link không phải của Xiaohongshu (xhslink.com / xiaohongshu.com).")
    return url


def _headers(mobile=False):
    h = {"User-Agent": UA_MOBILE if mobile else UA_DESKTOP, "Accept-Language": "zh-CN,zh;q=0.9,vi;q=0.8",
         "Referer": "https://www.xiaohongshu.com/"}
    ck = settings.xhs_cookie()
    if ck:
        h["Cookie"] = ck
    return h


def note_targets(url: str) -> tuple[str | None, list[str]]:
    """Từ link (kể cả trang đăng nhập rednote.com/login?redirectPath=...) -> mã bài viết + các link trang cần thử."""
    u = urlparse(url)
    q = parse_qs(u.query)
    if "/login" in u.path and q.get("redirectPath"):
        url = q["redirectPath"][0]
        u = urlparse(url)
        q = parse_qs(u.query)
    m = NOTE_RE.search(u.path)
    if not m:
        return None, [url]
    nid = m.group(1)
    keep = {k: v[0] for k, v in q.items() if k in ("xsec_token", "xsec_source", "share_id", "app_platform")}
    if "xsec_token" in keep:
        keep.setdefault("xsec_source", "app_share")
    qs = ("?" + urlencode(keep, quote_via=quote)) if keep else ""
    targets = [f"https://www.xiaohongshu.com/explore/{nid}{qs}",
               f"https://www.xiaohongshu.com/discovery/item/{nid}{qs}",
               f"https://www.rednote.com/explore/{nid}{qs}"]
    return nid, targets


def _is_login(resp) -> bool:
    return "/login" in str(resp.url) or "website-login" in resp.text[:20000]


def resolve(url: str) -> str:
    with httpx.Client(follow_redirects=True, headers=_headers(), timeout=20) as c:
        r = c.get(url)
        return str(r.url)


def _initial_state(html: str) -> dict | None:
    m = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*</script>", html, re.S)
    if not m:
        return None
    raw = re.sub(r"\bundefined\b", "null", m.group(1))
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _walk(o, key):
    if isinstance(o, dict):
        for k, v in o.items():
            if k == key:
                yield v
            yield from _walk(v, key)
    elif isinstance(o, list):
        for v in o:
            yield from _walk(v, key)


def _candidates_from_state(state: dict) -> tuple[list[str], str]:
    urls: list[str] = []
    title = ""
    for t in _walk(state, "title"):
        if isinstance(t, str) and t.strip():
            title = t.strip()
            break
    # 1) video gốc không watermark
    for key in _walk(state, "originVideoKey"):
        if isinstance(key, str) and key:
            urls.append(f"https://sns-video-bd.xhscdn.com/{key}")
    # 2) các luồng h264/h265 (chất lượng cao trước)
    streams = []
    for st in _walk(state, "stream"):
        if isinstance(st, dict):
            for codec in ("h264", "h265", "av1"):
                for s in st.get(codec) or []:
                    if isinstance(s, dict) and s.get("masterUrl"):
                        streams.append((s.get("height") or 0, s.get("videoBitrate") or 0, codec, s))
    streams.sort(key=lambda x: (x[0], x[1], x[2] == "h264"), reverse=True)  # độ phân giải, bitrate cao nhất trước
    for *_, s in streams:
        urls.append(s["masterUrl"])
        urls.extend(s.get("backupUrls") or [])
    seen, out = set(), []
    for u in urls:
        u = u.replace("http://", "https://")
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out, title


def _stream_to_file(url: str, dest: Path) -> bool:
    try:
        with httpx.Client(follow_redirects=True, headers=_headers(), timeout=60) as c:
            with c.stream("GET", url) as r:
                if r.status_code != 200 or "video" not in r.headers.get("content-type", "video"):
                    return False
                with open(dest, "wb") as f:
                    for chunk in r.iter_bytes(1 << 16):
                        f.write(chunk)
        return dest.exists() and dest.stat().st_size > 50_000
    except httpx.HTTPError:
        return False


def _via_page(url: str, dest: Path, mobile=False, flags=None) -> dict | None:
    with httpx.Client(follow_redirects=True, headers=_headers(mobile), timeout=20) as c:
        r = c.get(url)
    if flags is not None and _is_login(r):
        flags["login"] = True
    state = _initial_state(r.text)
    if not state:
        return None
    cands, title = _candidates_from_state(state)
    for i, u in enumerate(cands):
        if _stream_to_file(u, dest):
            return {"title": title, "source": "origin" if i == 0 and "sns-video-bd" in u else "stream",
                    "page_url": str(r.url)}
    return None


def _via_ytdlp(url: str, dest: Path) -> dict:
    import yt_dlp
    opts = {
        "outtmpl": str(dest.with_suffix(".%(ext)s")),
        "format": "bv*[height>=1080]+ba/bv*+ba/b", "format_sort": ["res", "br", "fps"],
        "merge_output_format": "mp4",
        "quiet": True, "no_warnings": True, "noplaylist": True,
        "http_headers": _headers(),
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
    files = sorted(dest.parent.glob(dest.stem + ".*"), key=lambda p: p.stat().st_size, reverse=True)
    files = [f for f in files if f.suffix in (".mp4", ".mkv", ".webm", ".mov")]
    if not files:
        raise DownloadError("yt-dlp không tải được video.")
    if files[0] != dest:
        files[0].rename(dest)
    return {"title": (info or {}).get("title", ""), "source": "yt-dlp", "page_url": url}


LOGIN_HELP = ("Xiaohongshu yêu cầu đăng nhập khi tải từ máy chủ ở nước ngoài (Colab/VPS). Cách xử lý: "
              "(1) Mở mục 'Cookie Xiaohongshu' ở bước 1 trên giao diện, dán cookie tài khoản Xiaohongshu của bạn rồi thử lại; "
              "hoặc (2) tải video về điện thoại/máy tính rồi bấm 'Tải file video lên'.")


def download(text: str, dest: Path, log=print) -> dict:
    url = extract_url(text)
    log(f"Link: {url}")
    try:
        full = resolve(url)
    except httpx.HTTPError as e:
        raise DownloadError(f"Không mở được link: {e}") from e
    nid, targets = note_targets(full)
    log(f"Mã bài viết: {nid or 'không rõ'} · cookie: {'có' if settings.xhs_cookie() else 'chưa có'}")
    errors, flags = [], {}
    for t in targets:
        for mobile in (False, True):
            try:
                res = _via_page(t, dest, mobile, flags)
                if res:
                    return res
            except Exception as e:  # noqa: BLE001
                errors.append(f"đọc trang: {str(e)[:80]}")
    for t in targets[:2]:
        try:
            return _via_ytdlp(t, dest)
        except Exception as e:  # noqa: BLE001
            errors.append(f"yt-dlp: {str(e)[:120]}")
    if flags.get("login") or "/login" in full:
        if settings.xhs_cookie():
            raise DownloadError("Cookie Xiaohongshu đã hết hạn hoặc không hợp lệ. Hãy đăng nhập lại và dán cookie mới, "
                                "hoặc tải video về máy rồi bấm 'Tải file video lên'.")
        raise DownloadError(LOGIN_HELP)
    raise DownloadError("Không tải được video (" + " | ".join(dict.fromkeys(errors))[:400] +
                        "). Bạn có thể tải video về máy rồi bấm 'Tải file video lên'.")
