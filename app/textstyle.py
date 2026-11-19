"""Kiểu chữ & font cho chữ Việt trên video (giống mục "Văn bản" của CapCut bản miễn phí).

- FONTS:   font Google Fonts đủ dấu tiếng Việt, tự tải về lần đầu dùng (data/fonts).
           Font riêng của bạn: bỏ .ttf/.otf vào thư mục fonts/ hoặc tải lên qua giao diện.
- PRESETS: kiểu chữ dựng sẵn (khung màu, viền, viền đôi, đổ bóng, neon, chuyển màu...).
- render_text(): vẽ chữ theo kiểu -> ảnh RGBA, dùng cho cả ảnh xem trước và video.
"""
from __future__ import annotations

import glob
import hashlib
import re
import threading
import urllib.parse
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .config import CACHE_DIR, DATA_DIR

FONT_CACHE = DATA_DIR / "fonts"
CUSTOM_DIRS = [Path(__file__).resolve().parent.parent / "fonts", FONT_CACHE / "custom"]
FONT_CACHE.mkdir(parents=True, exist_ok=True)
(FONT_CACHE / "custom").mkdir(parents=True, exist_ok=True)
PREVIEW_DIR = CACHE_DIR / "previews"
PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
GF = "https://raw.githubusercontent.com/google/fonts/main/"

# id: (tên hiển thị, nhóm, đường dẫn trong repo google/fonts, độ đậm cho font biến thiên)
FONTS = {
    "bevietnam": ("Be Vietnam Pro", "Cơ bản", "ofl/bevietnampro/BeVietnamPro-ExtraBold.ttf", None),
    "montserrat": ("Montserrat", "Cơ bản", "ofl/montserrat/Montserrat[wght].ttf", 800),
    "roboto": ("Roboto", "Cơ bản", "ofl/roboto/Roboto[wdth,wght].ttf", 800),
    "inter": ("Inter", "Cơ bản", "ofl/inter/Inter[opsz,wght].ttf", 800),
    "lexend": ("Lexend", "Cơ bản", "ofl/lexend/Lexend[wght].ttf", 700),
    "sourcesans": ("Source Sans 3", "Cơ bản", "ofl/sourcesans3/SourceSans3[wght].ttf", 800),
    "nunito": ("Nunito", "Tròn / dễ thương", "ofl/nunito/Nunito[wght].ttf", 900),
    "baloo": ("Baloo 2", "Tròn / dễ thương", "ofl/baloo2/Baloo2[wght].ttf", 800),
    "quicksand": ("Quicksand", "Tròn / dễ thương", "ofl/quicksand/Quicksand[wght].ttf", 700),
    "comfortaa": ("Comfortaa", "Tròn / dễ thương", "ofl/comfortaa/Comfortaa[wght].ttf", 700),
    "itim": ("Itim", "Tròn / dễ thương", "ofl/itim/Itim-Regular.ttf", None),
    "oswald": ("Oswald", "Tiêu đề", "ofl/oswald/Oswald[wght].ttf", 700),
    "anton": ("Anton", "Tiêu đề", "ofl/anton/Anton-Regular.ttf", None),
    "bangers": ("Bangers", "Tiêu đề", "ofl/bangers/Bangers-Regular.ttf", None),
    "bungee": ("Bungee", "Tiêu đề", "ofl/bungee/Bungee-Regular.ttf", None),
    "alfaslab": ("Alfa Slab One", "Tiêu đề", "ofl/alfaslabone/AlfaSlabOne-Regular.ttf", None),
    "paytone": ("Paytone One", "Tiêu đề", "ofl/paytoneone/PaytoneOne-Regular.ttf", None),
    "chakra": ("Chakra Petch", "Tiêu đề", "ofl/chakrapetch/ChakraPetch-Bold.ttf", None),
    "playfair": ("Playfair Display", "Có chân", "ofl/playfairdisplay/PlayfairDisplay[wght].ttf", 800),
    "lobster": ("Lobster", "Viết tay", "ofl/lobster/Lobster-Regular.ttf", None),
    "pacifico": ("Pacifico", "Viết tay", "ofl/pacifico/Pacifico-Regular.ttf", None),
    "dancing": ("Dancing Script", "Viết tay", "ofl/dancingscript/DancingScript[wght].ttf", 700),
    "charm": ("Charm", "Viết tay", "ofl/charm/Charm-Bold.ttf", None),
    "patrick": ("Patrick Hand", "Viết tay", "ofl/patrickhand/PatrickHand-Regular.ttf", None),
    "system": ("Noto Sans (có sẵn)", "Cơ bản", None, None),
}

# Thuộc tính kiểu chữ:
#  fg: màu chữ | grad: [màu trên, màu dưới] chữ chuyển màu
#  stroke: (màu, độ dày theo cỡ chữ) | stroke2: viền ngoài thứ 2
#  shadow: (màu, lệch x, lệch y, độ nhoè, độ đậm) | glow: (màu, bán kính)
#  bg: none | rect | round | pill  + bg_color, bg_alpha
PRESETS = {
    "yellow_box": {"name": "Khung vàng", "fg": "#000000", "bg": "round", "bg_color": "#F4C710"},
    "white_box": {"name": "Khung trắng", "fg": "#111111", "bg": "round", "bg_color": "#FFFFFF"},
    "black_box": {"name": "Khung đen mờ", "fg": "#FFFFFF", "bg": "round", "bg_color": "#000000", "bg_alpha": 0.65},
    "red_box": {"name": "Khung đỏ", "fg": "#FFFFFF", "bg": "round", "bg_color": "#FF2D55"},
    "pink_pill": {"name": "Nhãn hồng", "fg": "#FFFFFF", "bg": "pill", "bg_color": "#FF7EB3"},
    "blue_box": {"name": "Khung xanh dương", "fg": "#FFFFFF", "bg": "rect", "bg_color": "#1E6BFF"},
    "green_box": {"name": "Khung xanh lá", "fg": "#FFFFFF", "bg": "round", "bg_color": "#00B85C"},
    "purple_box": {"name": "Khung tím", "fg": "#FFFFFF", "bg": "pill", "bg_color": "#7C4DFF"},
    "outline_white": {"name": "Trắng viền đen", "fg": "#FFFFFF", "stroke": ("#000000", 0.12)},
    "outline_black": {"name": "Đen viền trắng", "fg": "#111111", "stroke": ("#FFFFFF", 0.12)},
    "outline_yellow": {"name": "Vàng viền đen", "fg": "#FFE600", "stroke": ("#000000", 0.12)},
    "outline_red": {"name": "Trắng viền đỏ", "fg": "#FFFFFF", "stroke": ("#E8112D", 0.12)},
    "sticker": {"name": "Sticker viền đôi", "fg": "#FFFFFF", "stroke": ("#FF2D55", 0.10), "stroke2": ("#FFFFFF", 0.10)},
    "sticker_blue": {"name": "Sticker xanh", "fg": "#FFE600", "stroke": ("#1E3A8A", 0.10), "stroke2": ("#FFFFFF", 0.10)},
    "shadow": {"name": "Đổ bóng", "fg": "#FFFFFF", "shadow": ("#000000", 0.06, 0.07, 0.07, 0.85)},
    "shadow_hard": {"name": "Bóng cứng", "fg": "#FFE600", "stroke": ("#000000", 0.08),
                    "shadow": ("#000000", 0.09, 0.09, 0.0, 1.0)},
    "neon_cyan": {"name": "Neon xanh", "fg": "#E8FFFF", "glow": ("#00E5FF", 0.35)},
    "neon_pink": {"name": "Neon hồng", "fg": "#FFF0F7", "glow": ("#FF2E9A", 0.35)},
    "fire": {"name": "Lửa", "grad": ["#FFE259", "#FF5A1F"], "stroke": ("#3A0A00", 0.10)},
    "candy": {"name": "Kẹo ngọt", "grad": ["#FF9AD5", "#8E5CFF"], "stroke": ("#FFFFFF", 0.11)},
    "ocean": {"name": "Đại dương", "grad": ["#7CF5FF", "#1E6BFF"], "stroke": ("#06204F", 0.10)},
    "plain_white": {"name": "Chữ trắng", "fg": "#FFFFFF"},
    "original": {"name": "Giữ màu chữ gốc", "fg": "#FFFFFF"},
}

_dl_lock = threading.Lock()
# đệm khung gọn khi "vừa chữ gốc": khung ôm sát chữ, không lấn ra hình
COMPACT_PAD = {"padx": 0.35, "pady": 0.16}


# ---------------- Font ----------------
def _custom_fonts():
    out = {}
    for d in CUSTOM_DIRS:
        if d.exists():
            for f in sorted(list(d.glob("*.ttf")) + list(d.glob("*.otf"))):
                out["custom:" + f.name] = f
    return out


def list_fonts():
    items = [{"id": k, "name": v[0], "group": v[1]} for k, v in FONTS.items()]
    items += [{"id": k, "name": p.stem, "group": "Font của bạn"} for k, p in _custom_fonts().items()]
    return items


def _system_font():
    for name in ("NotoSans-Bold.ttf", "DejaVuSans-Bold.ttf"):
        c = glob.glob(f"/usr/share/fonts/**/{name}", recursive=True)
        if c:
            return c[0]
    c = glob.glob("/usr/share/fonts/**/*.ttf", recursive=True)
    if c:
        return c[0]
    raise FileNotFoundError("Không có font nào. Cài fonts-noto-core.")


def font_path(font_id: str) -> tuple[str, int | None]:
    if font_id.startswith("custom:"):
        p = _custom_fonts().get(font_id)
        return (str(p), None) if p else (_system_font(), None)
    spec = FONTS.get(font_id)
    if not spec or not spec[2]:
        return _system_font(), None
    _, _, rel, weight = spec
    dest = FONT_CACHE / Path(rel).name
    if not dest.exists():
        with _dl_lock:
            if not dest.exists():
                try:
                    r = httpx.get(GF + urllib.parse.quote(rel), timeout=60, follow_redirects=True)
                    r.raise_for_status()
                    tmp = dest.with_suffix(".part")
                    tmp.write_bytes(r.content)
                    tmp.replace(dest)
                except Exception as e:  # noqa: BLE001
                    print(f"Không tải được font {font_id}: {e}")
                    return _system_font(), None
    return str(dest), weight


def load_font(font_id: str, size: int):
    path, weight = font_path(font_id)
    f = ImageFont.truetype(path, size)
    if weight:
        try:
            axes = f.get_variation_axes()
            vals = [max(a["minimum"], min(a["maximum"], weight)) if a["name"] in (b"Weight", "Weight")
                    else a["default"] for a in axes]
            f.set_variation_by_axes(vals)
        except Exception:  # noqa: BLE001
            pass
    return f


def save_custom_font(filename: str, data: bytes) -> str:
    name = re.sub(r"[^\w.\-]+", "_", Path(filename).name)
    if not name.lower().endswith((".ttf", ".otf")) or len(data) < 1000:
        raise ValueError("Chỉ nhận file font .ttf hoặc .otf")
    p = FONT_CACHE / "custom" / name
    p.write_bytes(data)
    try:
        ImageFont.truetype(str(p), 20)
    except Exception as e:
        p.unlink(missing_ok=True)
        raise ValueError(f"File font không hợp lệ: {e}") from e
    return "custom:" + name


# ---------------- Kiểu chữ ----------------
def _hex(h, default=(255, 255, 255)):
    h = (h or "").strip().lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) if re.fullmatch(r"[0-9a-fA-F]{6}", h) else default


def list_presets():
    return [{"id": k, "name": v["name"]} for k, v in PRESETS.items()]


def resolve_style(preset, text_color="", bg_color="", stroke_color="", bg_opacity=-1.0, bg_mode="preset"):
    """Kiểu dựng sẵn + chỉnh của người dùng.

    bg_mode: preset = theo kiểu chữ | none = không nền, chỉ hiện chữ | color = có nền màu bg_color
    """
    st = dict(PRESETS.get(preset) or PRESETS["yellow_box"])
    if text_color:
        st["fg"] = text_color
        st.pop("grad", None)
    if stroke_color:
        w = st.get("stroke", (None, 0.10))[1]
        st["stroke"] = (stroke_color, w)
    if bg_mode == "none":
        st["bg"] = "none"
        if not (st.get("stroke") or st.get("glow") or st.get("shadow")):
            # không nền: thêm viền mảnh màu tương phản để chữ đọc được trên mọi cảnh
            r, g, b = _hex(st.get("fg", "#FFFFFF"))
            st["stroke"] = ("#000000" if 0.299 * r + 0.587 * g + 0.114 * b > 128 else "#FFFFFF", 0.07)
    elif bg_mode == "color":
        if st.get("bg", "none") == "none":
            st["bg"] = "round"
        st["bg_color"] = bg_color or st.get("bg_color", "#000000")
    elif bg_color:
        st["bg_color"] = bg_color
        if st.get("bg", "none") == "none":
            st["bg"] = "round"
    if st.get("bg", "none") != "none" and bg_opacity is not None and bg_opacity >= 0:
        st["bg_alpha"] = max(0.0, min(1.0, bg_opacity))
    return st


def wrap_text(text, font, max_w):
    lines, cur = [], ""
    for w in text.split():
        t = (cur + " " + w).strip()
        if font.getlength(t) <= max_w or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [text]


def block_size(lines, font, size, style):
    """Kích thước (rộng, cao) của khối chữ đã vẽ, gồm cả khung nền."""
    asc, desc = font.getmetrics()
    lh = int((asc + desc) * 1.08)
    tw = max(int(font.getlength(l)) for l in lines)
    padx, pady = _pads(size, style)
    return tw + 2 * padx, lh * len(lines) + 2 * pady


def _pads(size, style):
    if style.get("bg", "none") != "none":
        return int(size * style.get("padx", 0.9)), int(size * style.get("pady", 0.5))
    sw = int(size * style["stroke"][1]) if style.get("stroke") else 0
    sw2 = int(size * style["stroke2"][1]) if style.get("stroke2") else 0
    glow = int(size * style["glow"][1]) if style.get("glow") else 0
    sh = style.get("shadow")
    shp = int(size * (max(sh[1], sh[2]) + sh[3])) if sh else 0
    p = sw + sw2 + glow + shp + 2
    return p, p


def fit_text(text, font_id, size0, max_w, max_lines, style, max_h=None, min_scale=0.55):
    """Giảm cỡ chữ đến khi vừa: không quá max_lines dòng, rộng <= max_w, cao <= max_h (nếu có)."""
    size = size0
    while True:
        font = load_font(font_id, size)
        padx, _ = _pads(size, style)
        lines = wrap_text(text, font, max(20, max_w - 2 * padx))
        w, h = block_size(lines, font, size, style)
        ok = len(lines) <= max_lines and w <= max_w * 1.02 and (max_h is None or h <= max_h)
        if ok or size <= max(8, size0 * min_scale):
            return font, size, lines
        size = max(8, int(size * 0.93))


def _mask(lines, font, widths, lh, ox, oy, W, H, stroke=0):
    m = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(m)
    for i, l in enumerate(lines):
        d.text((ox + (W - 2 * ox - widths[i]) // 2, oy + i * lh), l, font=font, fill=255,
               stroke_width=stroke, stroke_fill=255)
    return m


def render_text(lines, font, size, style, min_w=0, min_h=0):
    asc, desc = font.getmetrics()
    lh = int((asc + desc) * 1.08)
    widths = [int(font.getlength(l)) for l in lines]
    tw, th = max(widths), lh * len(lines)
    sw = int(size * style["stroke"][1]) if style.get("stroke") else 0
    sw2 = int(size * style["stroke2"][1]) if style.get("stroke2") else 0
    glow = int(size * style["glow"][1]) if style.get("glow") else 0
    sh = style.get("shadow")
    shx, shy, shb = (int(size * sh[1]), int(size * sh[2]), int(size * sh[3])) if sh else (0, 0, 0)
    bg = style.get("bg", "none")
    padx, pady = _pads(size, style)
    W = max(tw + 2 * padx, int(min_w))
    H = max(th + 2 * pady, int(min_h))
    ox, oy = (W - tw) // 2, (H - th) // 2
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    if bg != "none":
        col = _hex(style.get("bg_color"), (244, 199, 16))
        alpha = int(255 * style.get("bg_alpha", 1.0))
        r = {"rect": size * 0.12, "round": min(H * 0.28, size * 1.2), "pill": H / 2}[bg] if bg in ("rect", "round", "pill") else 0
        SS = 4
        m = Image.new("L", (W * SS, H * SS), 0)
        ImageDraw.Draw(m).rounded_rectangle((0, 0, W * SS - 1, H * SS - 1), radius=int(min(r, H / 2, W / 2) * SS), fill=alpha)
        m = m.resize((W, H), Image.LANCZOS)
        layer = Image.new("RGBA", (W, H), col + (0,))
        layer.putalpha(m)
        canvas = Image.alpha_composite(canvas, layer)

    def solid(color, mask, opacity=1.0):
        layer = Image.new("RGBA", (W, H), _hex(color, (0, 0, 0)) + (0,))
        layer.putalpha(mask.point(lambda v: int(v * opacity)))
        return layer

    text_m = _mask(lines, font, widths, lh, ox, oy, W, H)
    outer_w = sw + sw2
    outer_m = _mask(lines, font, widths, lh, ox, oy, W, H, outer_w) if outer_w else text_m

    if sh:
        m = Image.new("L", (W, H), 0)
        m.paste(outer_m, (shx, shy))
        if shb:
            m = m.filter(ImageFilter.GaussianBlur(shb))
        canvas = Image.alpha_composite(canvas, solid(sh[0], m, sh[4]))
    if glow:
        g = style["glow"][0]
        for rad, op in ((glow, 0.9), (glow / 2, 0.9), (glow / 5, 1.0)):
            canvas = Image.alpha_composite(canvas, solid(g, text_m.filter(ImageFilter.GaussianBlur(max(1, rad))), op))
    if sw2:
        canvas = Image.alpha_composite(canvas, solid(style["stroke2"][0], outer_m))
    if sw:
        canvas = Image.alpha_composite(canvas, solid(style["stroke"][0], _mask(lines, font, widths, lh, ox, oy, W, H, sw)))
    if style.get("grad"):
        c1, c2 = _hex(style["grad"][0]), _hex(style["grad"][1])
        grad = Image.new("RGBA", (1, H))
        for y in range(H):
            u = min(1.0, max(0.0, (y - oy) / max(1, th)))
            grad.putpixel((0, y), tuple(int(c1[i] * (1 - u) + c2[i] * u) for i in range(3)) + (255,))
        grad = grad.resize((W, H))
        grad.putalpha(text_m)
        canvas = Image.alpha_composite(canvas, grad)
    else:
        canvas = Image.alpha_composite(canvas, solid(style.get("fg", "#FFFFFF"), text_m))
    return canvas


# ---------------- Ảnh xem trước ----------------
def preview_png(text, preset, font_id, text_color="", bg_color="", stroke_color="", bg_opacity=-1.0,
                size=64, max_w=900, bg_mode="preset", compact=False) -> Path:
    key = hashlib.md5(repr((text, preset, font_id, text_color, bg_color, stroke_color, bg_opacity, size, max_w,
                            bg_mode, compact, PRESETS.get(preset), 2)).encode()).hexdigest()
    p = PREVIEW_DIR / f"{key}.png"
    if not p.exists():
        st = resolve_style(preset, text_color, bg_color, stroke_color, bg_opacity, bg_mode)
        if compact:
            st.update(COMPACT_PAD)
        font, sz, lines = fit_text(text, font_id, size, max_w, 3, st)
        render_text(lines, font, sz, st).save(p)
    return p


def download_all():
    for k in FONTS:
        print(k, font_path(k)[0])


if __name__ == "__main__":
    download_all()
