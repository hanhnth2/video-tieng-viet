"""Thêm khung chữ bằng tay: khi máy dò sót chữ Trung, bạn quét khung trên khung hình rồi điền chữ Việt."""
from __future__ import annotations

import cv2
import numpy as np

from . import onscreen

PREVIEW_W = 540


def _read_frame(src, t):
    cap = cv2.VideoCapture(str(src))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(t * fps)))
    ok, fr = cap.read()
    cap.release()
    return fr if ok else None


def frame_jpeg(src, t) -> bytes | None:
    """Ảnh khung hình tại giây t (thu nhỏ) để quét khung chữ trên giao diện."""
    fr = _read_frame(src, t)
    if fr is None:
        return None
    h, w = fr.shape[:2]
    if w > PREVIEW_W:
        fr = cv2.resize(fr, (PREVIEW_W, int(h * PREVIEW_W / w)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", fr, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return buf.tobytes() if ok else None


def _px(box, w, h):
    x0, y0, x1, y1 = [min(1.0, max(0.0, float(v))) for v in box]
    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    return int(x0 * w), int(y0 * h), max(int(x0 * w) + 2, int(x1 * w)), max(int(y0 * h) + 2, int(y1 * h))


def time_range(src, t, box, end_t=None, thr=16.0):
    """Đoán khoảng thời gian khung chữ hiện trên hình: vùng ảnh trong khung giữ gần như nguyên quanh giây t."""
    cap = cv2.VideoCapture(str(src))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    step = max(1, int(round(fps / 4)))
    feats, times = [], []
    i = 0
    while True:
        ok = cap.grab()
        if not ok:
            break
        if i % step == 0:
            ok, fr = cap.retrieve()
            if not ok:
                break
            h, w = fr.shape[:2]
            x0, y0, x1, y1 = _px(box, w, h)
            g = cv2.cvtColor(fr[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
            feats.append(cv2.resize(g, (64, max(8, int(64 * g.shape[0] / max(1, g.shape[1]))))).astype(np.float32))
            times.append(i / fps)
        i += 1
        if n and i >= n:
            break
    cap.release()
    if not feats:
        return max(0.0, t - 1), t + 1
    k = int(np.argmin([abs(x - t) for x in times]))
    ref = feats[k]
    a = b = k
    while a > 0 and np.abs(feats[a - 1] - ref).mean() < thr:
        a -= 1
    while b < len(feats) - 1 and np.abs(feats[b + 1] - ref).mean() < thr:
        b += 1
    t0, t1 = max(0.0, times[a] - 0.1), times[b] + 0.25
    if end_t:
        t1 = min(t1, end_t)
    return round(t0, 2), round(t1, 2)


def read_text(src, t, box):
    """Đọc chữ Trung trong khung đã quét (OCR)."""
    fr = _read_frame(src, t)
    if fr is None:
        return ""
    h, w = fr.shape[:2]
    x0, y0, x1, y1 = _px(box, w, h)
    pad = int(0.15 * (y1 - y0))
    crop = fr[max(0, y0 - pad):min(h, y1 + pad), max(0, x0 - pad):min(w, x1 + pad)]
    if crop.size == 0:
        return ""
    if crop.shape[0] < 48:   # chữ nhỏ: phóng to cho OCR đọc chắc hơn
        s = 48 / crop.shape[0]
        crop = cv2.resize(crop, (int(crop.shape[1] * s), 48), interpolation=cv2.INTER_CUBIC)
    dets = [d for d in onscreen.ocr_frame(crop, 0.15) if not d["wm"]]
    if not dets:
        return ""
    text, _ = onscreen._join_parts(dets)
    return text


def make_track(src, info, item: dict):
    """Tạo 1 đoạn chữ (track) giống như máy dò ra, theo khung bạn quét. Toạ độ theo khung hình xuất (info W/H)."""
    t = float(item.get("t", 0))
    t0, t1 = float(item.get("t0", t)), float(item.get("t1", t + 2))
    if t1 <= t0:
        t1 = t0 + 1.0
    W, H = info["W"], info["H"]
    x0, y0, x1, y1 = _px(item["box"], W, H)
    bw, bh = x1 - x0, y1 - y0
    vi = str(item.get("vi", "")).strip()[:300]
    # số dòng: ít dòng nhất mà vẫn chứa hết chữ Việt (ước lượng 1 ký tự rộng ~0.5 cỡ chữ)
    nlines = 1
    for k in range(1, 5):
        if bw / (0.5 * bh / k) * k >= max(1, len(vi)):
            nlines = k
            break
    else:
        nlines = 4
    line_h = bh / nlines
    fr = _read_frame(src, t)
    style = {"color": (255, 255, 255), "bg": (0, 0, 0), "bold": True, "contrast": 255.0}
    if fr is not None:
        fh, fw = fr.shape[:2]
        style = onscreen.estimate_style(fr, list(_px(item["box"], fw, fh)))
    box = [float(x0), float(y0), float(x1), float(y1)]
    zh = str(item.get("zh", "")).strip() or "(khung thêm tay)"
    return {"obs": [(t0, box, line_h, nlines, 1.0), (t1, box, line_h, nlines, 1.0)], "texts": [zh], "text": zh,
            "wm": False, "red_only": False, "ref": np.array(box), "line_h": float(line_h), "n": nlines, "static": True,
            "t0": t0, "t1": t1, "kind": "overlay", "score": 1.0, "why": ["thêm tay"], "angles": [0.0],
            "style": style, "vi": vi, "skip": False, "manual": True, "erase_only": not vi}


def save_crop(src, item, path):
    fr = _read_frame(src, float(item.get("t", 0)))
    if fr is None:
        return False
    h, w = fr.shape[:2]
    x0, y0, x1, y1 = _px(item["box"], w, h)
    p = int(0.3 * (y1 - y0))
    crop = fr[max(0, y0 - p):min(h, y1 + p), max(0, x0 - p):min(w, x1 + p)]
    if crop.size == 0:
        return False
    sc = min(1.0, 420 / crop.shape[1], 160 / crop.shape[0])
    crop = cv2.resize(crop, (max(1, int(crop.shape[1] * sc)), max(1, int(crop.shape[0] * sc))))
    path.parent.mkdir(parents=True, exist_ok=True)
    return bool(cv2.imwrite(str(path), crop, [cv2.IMWRITE_JPEG_QUALITY, 85]))
