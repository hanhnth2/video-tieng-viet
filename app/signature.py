"""Chữ ký / tên chủ sở hữu chèn lên video (vd "@Ngô Thị Hồng Hạnh") kèm hiệu ứng chuyển động.

Hiệu ứng:
  static   Đứng yên
  breathe  Mờ ảo (sáng - mờ theo nhịp thở)
  marquee  Chạy ngang (từ phải sang trái)
  bounce   Trôi nảy khắp màn hình (khó cắt xén)
  hop      Đổi góc mỗi 5 giây (khó xoá)
  blink    Hiện rồi ẩn định kỳ
  pop      Nảy vào (phóng to rồi về cỡ chuẩn, lặp lại mỗi 12 giây)
"""
from __future__ import annotations

import math

import cv2
import numpy as np

from . import textstyle

EFFECTS = {
    "static": "Đứng yên",
    "breathe": "Mờ ảo (nhịp thở)",
    "marquee": "Chạy ngang",
    "bounce": "Trôi nảy khắp màn hình",
    "hop": "Đổi góc mỗi 5 giây",
    "blink": "Hiện / ẩn định kỳ",
    "pop": "Nảy vào",
}
POSITIONS = {
    "top-left": "Góc trên trái", "top-center": "Giữa phía trên", "top-right": "Góc trên phải",
    "center": "Chính giữa",
    "bottom-left": "Góc dưới trái", "bottom-center": "Giữa phía dưới", "bottom-right": "Góc dưới phải",
}


def _smooth(u):
    u = min(1.0, max(0.0, u))
    return u * u * (3 - 2 * u)


class Signature:
    def __init__(self, opts, W, H):
        self.W, self.H = W, H
        self.effect = opts.wm_effect if opts.wm_effect in EFFECTS else "static"
        self.pos = opts.wm_position if opts.wm_position in POSITIONS else "bottom-right"
        self.opacity = min(1.0, max(0.1, opts.wm_opacity))
        st = textstyle.resolve_style(opts.wm_preset, opts.wm_color, "", "", -1, "preset")
        size = max(12, int(min(W, H) * opts.wm_size))
        text = opts.wm_text.strip()
        while True:
            font = textstyle.load_font(opts.wm_font, size)
            img = textstyle.render_text([text], font, size, st)
            if img.width <= W * 0.9 or size <= 12 or self.effect == "marquee":
                break
            size = int(size * 0.9)
        arr = np.array(img)
        self.bgr = arr[..., [2, 1, 0]].astype(np.float32)
        self.a = arr[..., 3:4].astype(np.float32) / 255.0
        self.h, self.w = self.a.shape[:2]
        self.m = int(min(W, H) * 0.035)

    # vị trí góc trên-trái của chữ ký cho mỗi điểm neo
    def _anchor(self, pos, w=None, h=None):
        w, h, W, H, m = w or self.w, h or self.h, self.W, self.H, self.m
        x = {"left": m, "center": (W - w) / 2, "right": W - w - m}
        y = {"top": m, "center": (H - h) / 2, "bottom": H - h - m}
        if pos == "center":
            return x["center"], y["center"]
        v, hz = pos.split("-")
        return x[hz], y[v]

    def draw(self, frame, t):
        bgr, a, w, h = self.bgr, self.a, self.w, self.h
        alpha = self.opacity
        e = self.effect
        if e == "breathe":
            alpha *= 0.35 + 0.65 * (0.5 + 0.5 * math.cos(2 * math.pi * t / 3.0))
            x, y = self._anchor(self.pos)
        elif e == "marquee":
            speed = self.W / 7.0
            x = self.W - (t * speed) % (self.W + w)
            row = self.pos.split("-")[0] if "-" in self.pos else "center"
            _, y = self._anchor(f"{row}-left" if row != "center" else "center")
        elif e == "bounce":
            def tri(p, L):
                return L - abs((p % (2 * L)) - L) if L > 0 else 0
            x = tri(t * self.W * 0.11 + self.W * 0.3, self.W - w)
            y = tri(t * self.H * 0.07 + self.H * 0.6, self.H - h)
        elif e == "hop":
            corners = ["top-left", "top-right", "bottom-right", "bottom-left"]
            k = int(t // 5.0)
            ph = t - k * 5.0
            x, y = self._anchor(corners[k % 4])
            alpha *= _smooth(ph / 0.4) * _smooth((5.0 - ph) / 0.4)
        elif e == "blink":
            ph = t % 8.0
            alpha *= _smooth(ph / 0.5) * _smooth((3.5 - ph) / 0.5) if ph < 3.5 else 0.0
            x, y = self._anchor(self.pos)
        elif e == "pop":
            ph = t % 12.0
            if ph < 0.6:
                u = ph / 0.6
                sc = 0.3 + 0.85 * _smooth(u / 0.7) - 0.15 * _smooth((u - 0.7) / 0.3)
                alpha *= _smooth(u / 0.4)
                nw, nh = max(2, int(w * sc)), max(2, int(h * sc))
                bgr = cv2.resize(self.bgr, (nw, nh))
                a = cv2.resize(self.a, (nw, nh))[..., None]
                bx, by = self._anchor(self.pos)
                x, y = bx + (w - nw) / 2, by + (h - nh) / 2
            else:
                x, y = self._anchor(self.pos)
        else:
            x, y = self._anchor(self.pos)
        if alpha <= 0.01:
            return
        _blend(frame, bgr, a * alpha, int(round(x)), int(round(y)))


def _blend(frame, bgr, a, x, y):
    """Dán ảnh có kênh alpha tại (x, y), tự cắt phần nằm ngoài khung hình."""
    H, W = frame.shape[:2]
    h, w = a.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + w), min(H, y + h)
    if x1 <= x0 or y1 <= y0:
        return
    sa = a[y0 - y:y1 - y, x0 - x:x1 - x]
    sb = bgr[y0 - y:y1 - y, x0 - x:x1 - x]
    roi = frame[y0:y1, x0:x1].astype(np.float32)
    frame[y0:y1, x0:x1] = (roi * (1 - sa) + sb * sa).astype(np.uint8)


def build(opts, W, H):
    if not opts.wm_enabled or not opts.wm_text.strip():
        return None
    return Signature(opts, W, H)
