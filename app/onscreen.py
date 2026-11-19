"""Chữ trên hình + logo Xiaohongshu.

- Dò chữ Trung bằng RapidOCR, theo dõi qua các khung hình, dịch và vẽ chữ Việt đè lên.
- Dò watermark Xiaohongshu (chữ 小红书 / 小红书号 + logo đỏ) -> chỉ xoá, không vẽ gì thêm.
- Dò đoạn outro logo Xiaohongshu ở cuối video -> cắt bỏ.
"""
from __future__ import annotations

import difflib
import re
import statistics
import subprocess
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

CJK = re.compile(r"[一-鿿]")
WM_RE = re.compile(r"小红书|小紅書|红书号|紅書號|xiaohongshu|\bRED\b|^RED", re.I)
ID_RE = re.compile(r"^[\s:：#@ID号]*\d{5,}[\s]*$", re.I)
BOLD_RATIO = 0.27
_reader = None


def get_reader():
    global _reader
    if _reader is None:
        try:
            from rapidocr import RapidOCR  # gói mới (Python 3.12+)
        except ImportError:
            from rapidocr_onnxruntime import RapidOCR  # gói cũ
        _reader = RapidOCR()
    return _reader


def _run_ocr(img):
    """Trả về [(pts, text, conf)] cho cả rapidocr mới và rapidocr_onnxruntime cũ."""
    res = get_reader()(img)
    if isinstance(res, tuple):  # bản cũ: (list, elapse)
        return res[0] or []
    boxes, txts, scores = getattr(res, "boxes", None), getattr(res, "txts", None), getattr(res, "scores", None)
    if boxes is None or txts is None:
        return []
    return list(zip(boxes, txts, scores))


# ======================= Dò chữ =======================
def ocr_frame(frame, min_conf):
    H, W = frame.shape[:2]
    sc = min(1.0, 1920.0 / max(W, H))
    img = cv2.resize(frame, (int(W * sc), int(H * sc))) if sc < 1 else frame
    raw = []
    for pts, text, conf in _run_ocr(img):
        text = text.strip()
        conf = float(conf)
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        box = [min(xs) / sc, min(ys) / sc, max(xs) / sc, max(ys) / sc]
        try:
            p0, p1, p3 = pts[0], pts[1], pts[3]
            ang = float(np.degrees(np.arctan2(p1[1] - p0[1], p1[0] - p0[0])))
            qh = float(np.hypot(p3[0] - p0[0], p3[1] - p0[1])) / sc
        except Exception:  # noqa: BLE001
            ang, qh = 0.0, box[3] - box[1]
        raw.append({"box": box, "text": text, "conf": conf, "wm": bool(WM_RE.search(text)), "angle": ang, "qh": qh})
    # dòng chỉ có số (ID tài khoản) nằm sát watermark -> cũng là watermark
    wms = [d for d in raw if d["wm"]]
    for d in raw:
        if d["wm"] or not ID_RE.match(d["text"]):
            continue
        for w in wms:
            lh = w["box"][3] - w["box"][1]
            if abs(d["box"][1] - w["box"][3]) < 2.5 * lh or abs(w["box"][1] - d["box"][3]) < 2.5 * lh:
                if min(d["box"][2], w["box"][2] + 3 * lh) > max(d["box"][0], w["box"][0] - 3 * lh):
                    d["wm"] = True
                    break
    out = []
    for d in raw:
        if d["wm"]:
            if d["conf"] >= 0.2:
                out.append(d)
        elif d["conf"] >= min_conf and CJK.search(d["text"]):
            out.append(d)
    return out


def xhs_red_mask(frame):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    return (((h <= 6) | (h >= 170)) & (s > 150) & (v > 170)).astype(np.uint8)


def red_logo_boxes(frame):
    """Tìm khối logo đỏ (nền đỏ bo góc, chữ trắng) gần các góc hình."""
    H, W = frame.shape[:2]
    m = xhs_red_mask(frame)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(m, 8)
    out = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if h == 0:
            continue
        ar = w / h
        frac = (w * h) / (W * H)
        cx, cy = x + w / 2, y + h / 2
        near_edge = (cx < 0.4 * W or cx > 0.6 * W) and (cy < 0.3 * H or cy > 0.7 * H)
        if 0.0006 < frac < 0.02 and 1.2 < ar < 4.0 and area / (w * h) > 0.55 and near_edge:
            out.append({"box": [float(x), float(y), float(x + w), float(y + h)],
                        "text": "#redlogo", "conf": 0.5, "wm": True, "red": True})
    return out


def _can_merge(a, b):
    """Hai khối chữ có thuộc cùng một đoạn không (cùng hàng, chồng lên nhau, hoặc dòng liền kề)."""
    if a["wm"] != b["wm"] or a.get("red") or b.get("red"):
        return False
    ha, hb = a["line_h"], b["line_h"]
    if not 0.55 < ha / hb < 1.8:
        return False
    A, B = a["box"], b["box"]
    h = min(ha, hb)
    H = max(ha, hb)
    v_ov = min(A[3], B[3]) - max(A[1], B[1])          # phần chồng theo chiều dọc
    gx = max(B[0] - A[2], A[0] - B[2])                 # khoảng cách ngang (âm = chồng nhau)
    x_ov = min(A[2], B[2]) - max(A[0], B[0])
    # 1) cùng một hàng, cách nhau khoảng trắng (vd "瘦腿　开髋　拉长线条")
    if v_ov > 0.5 * h and gx < 1.6 * H:
        return True
    # 2) hai khung chồng lên nhau đáng kể
    inter = max(0, x_ov) * max(0, v_ov)
    small = min((A[2] - A[0]) * (A[3] - A[1]), (B[2] - B[0]) * (B[3] - B[1]))
    if small > 0 and inter / small > 0.3:
        return True
    # 3) dòng trên - dòng dưới của cùng một đoạn
    top, bot = (A, B) if A[1] <= B[1] else (B, A)
    vgap = bot[1] - top[3]
    if -0.4 * H <= vgap <= 0.9 * H:
        if x_ov > 0.4 * min(A[2] - A[0], B[2] - B[0]):
            return True
        if a["wm"] and x_ov > -2 * H:
            return True
    return False


def _join_parts(parts):
    """Ghép chữ theo thứ tự đọc: nhóm theo hàng (trên -> dưới), trong hàng trái -> phải."""
    rows = []
    for p in sorted(parts, key=lambda p: (p["box"][1] + p["box"][3]) / 2):
        cy = (p["box"][1] + p["box"][3]) / 2
        hh = p["box"][3] - p["box"][1]
        for r in rows:
            if abs(cy - r["cy"]) < 0.5 * max(hh, r["h"]):
                r["parts"].append(p)
                break
        else:
            rows.append({"cy": cy, "h": hh, "parts": [p]})
    lines = [" ".join(p["text"] for p in sorted(r["parts"], key=lambda p: p["box"][0])) for r in rows]
    out = ""
    for l in lines:
        if out and not (CJK.search(out[-1]) and CJK.search(l[:1])):
            out += " "
        out += l
    return out, len(rows)


def merge_blocks(dets):
    blocks = []
    for d in dets:
        h = max(1.0, d["box"][3] - d["box"][1])
        blocks.append({"box": list(d["box"]), "parts": [d], "hs": [h], "line_h": h, "conf": d["conf"],
                       "wm": d["wm"], "red": d.get("red", False)})
    merged = True
    while merged:  # gộp lặp lại đến khi không còn cặp nào gộp được
        merged = False
        for i in range(len(blocks)):
            for j in range(i + 1, len(blocks)):
                a, b = blocks[i], blocks[j]
                if _can_merge(a, b):
                    a["box"] = [min(a["box"][0], b["box"][0]), min(a["box"][1], b["box"][1]),
                                max(a["box"][2], b["box"][2]), max(a["box"][3], b["box"][3])]
                    a["parts"] += b["parts"]
                    a["hs"] += b["hs"]
                    a["line_h"] = statistics.median(a["hs"])
                    a["conf"] = min(a["conf"], b["conf"])
                    del blocks[j]
                    merged = True
                    break
            if merged:
                break
    for b in blocks:
        b["text"], b["n"] = _join_parts(b["parts"])
        b["angle"] = max((abs(p.get("angle", 0.0)) for p in b["parts"]), default=0.0)
        if b.get("red"):
            b["text"] = "#redlogo"
    return blocks


def box_iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def estimate_style(frame, box):
    H, W = frame.shape[:2]
    x1, y1 = max(0, int(box[0])), max(0, int(box[1]))
    x2, y2 = min(W, int(box[2])), min(H, int(box[3]))
    crop = frame[y1:y2, x1:x2]
    if crop.shape[0] < 3 or crop.shape[1] < 3:
        return {"color": (255, 255, 255), "bg": (0, 0, 0), "bold": False, "contrast": 255.0}
    px = crop.reshape(-1, 3).astype(np.float32)
    if len(px) > 6000:
        px = px[np.random.RandomState(0).choice(len(px), 6000, replace=False)]
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)
    _, labels, centers = cv2.kmeans(px, 2, None, crit, 3, cv2.KMEANS_PP_CENTERS)
    counts = np.bincount(labels.ravel(), minlength=2)
    ti = int(np.argmin(counts))
    bi = 1 - ti
    lab = labels.ravel()
    fg_std = float(px[lab == ti].std(0).mean()) if counts[ti] > 3 else 99.0
    bg_std = float(px[lab == bi].std(0).mean()) if counts[bi] > 3 else 99.0
    lum = lambda c: 0.114 * c[0] + 0.587 * c[1] + 0.299 * c[2]  # noqa: E731
    return {"color": tuple(int(v) for v in centers[ti]), "bg": tuple(int(v) for v in centers[bi]),
            "bold": bool(counts[ti] / counts.sum() > BOLD_RATIO), "fg_std": fg_std, "bg_std": bg_std,
            "contrast": float(abs(lum(centers[ti]) - lum(centers[bi])))}


def update_tracks(tracks, active, si, t, blocks, frame):
    matched = set()
    for b in blocks:
        best, bs = None, 0.0
        for tr in active:
            if id(tr) in matched or tr["wm"] != b["wm"]:
                continue
            iou = box_iou(tr["last_box"], b["box"])
            sim = 1.0 if b["wm"] else difflib.SequenceMatcher(None, tr["last_text"], b["text"]).ratio()
            if iou >= 0.2 and sim >= 0.4 and iou + sim > bs:
                best, bs = tr, iou + sim
        if best is None:
            best = {"obs": [], "texts": [], "wm": b["wm"], "red_only": b.get("red", False)}
            tracks.append(best)
            active.append(best)
        if not b.get("red"):
            best["red_only"] = False
        best["obs"].append((t, list(b["box"]), b["line_h"], b["n"], b["conf"]))
        best.setdefault("angles", []).append(b.get("angle", 0.0))
        best["texts"].append(b["text"])
        best["last_box"], best["last_text"], best["last_i"] = b["box"], b["text"], si
        if len(best["obs"]) in (1, 2):
            best["style"] = estimate_style(frame, b["box"])
        matched.add(id(best))
    active[:] = [tr for tr in active if si - tr["last_i"] <= 3]


def box_at(tr, t):
    if tr["static"]:
        return tr["ref"]
    obs = tr["obs"]
    if t <= obs[0][0]:
        return np.array(obs[0][1])
    if t >= obs[-1][0]:
        return np.array(obs[-1][1])
    for a, b in zip(obs, obs[1:]):
        if a[0] <= t <= b[0]:
            u = (t - a[0]) / max(1e-6, b[0] - a[0])
            return np.array(a[1]) * (1 - u) + np.array(b[1]) * u
    return tr["ref"]


def _refine_cut(video, fps, t_good, t_outro):
    """Tìm đúng khung hình bắt đầu outro giữa 2 lần lấy mẫu (theo đột biến màu / tỉ lệ đỏ)."""
    cap = cv2.VideoCapture(str(video))
    i0, i1 = int(round(t_good * fps)), int(round(t_outro * fps))
    cap.set(cv2.CAP_PROP_POS_FRAMES, i0)
    prev, best, best_i = None, -1.0, i1
    for i in range(i0, i1 + 1):
        ok, fr = cap.read()
        if not ok:
            break
        small = cv2.resize(fr, (64, 64)).astype(np.float32)
        if xhs_red_mask(fr).mean() > 0.22:
            best_i = i
            break
        if prev is not None:
            diff = float(np.abs(small - prev).mean())
            if diff > best:
                best, best_i = diff, i
        prev = small
    cap.release()
    return best_i / fps


# ======================= Phân tích cả video =======================
def analyze(video: Path, opts, log=print):
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    nframes = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = nframes / fps if nframes else 0
    step = max(1, round(fps / opts.sample_fps))
    dt = step / fps
    tracks, active, samples = [], [], []
    idx = si = 0
    need_ocr = opts.replace_text or opts.remove_logo or opts.trim_outro
    while need_ocr:
        if not cap.grab():
            break
        if idx % step == 0:
            ok, frame = cap.retrieve()
            if ok:
                dets = ocr_frame(frame, opts.min_ocr_conf)
                if not opts.replace_text:
                    dets = [d for d in dets if d["wm"]]
                if opts.remove_logo:
                    dets += red_logo_boxes(frame)
                else:
                    dets = [d for d in dets if not d["wm"]]
                t = idx / fps
                blocks = merge_blocks(dets)
                update_tracks(tracks, active, si, t, blocks, frame)
                # dữ liệu để dò outro
                big_wm = any(b["wm"] and not b.get("red") and (b["box"][3] - b["box"][1]) > 0.035 * H
                             and 0.15 * W < (b["box"][0] + b["box"][2]) / 2 < 0.85 * W
                             and 0.2 * H < (b["box"][1] + b["box"][3]) / 2 < 0.8 * H for b in blocks)
                samples.append({"t": t, "red": float(xhs_red_mask(frame).mean()),
                                "big_wm": big_wm, "dark": float(frame.mean()) < 18})
                si += 1
                if nframes and si % 40 == 0:
                    log(f"  dò chữ {min(100, round(100 * idx / nframes))}%")
        idx += 1
    cap.release()
    if not duration:
        duration = idx / fps

    # ---- outro ----
    trim_at = None
    if opts.trim_outro and samples:
        last_t = samples[-1]["t"]
        j = len(samples)
        hit = False
        while j > 0:
            s = samples[j - 1]
            if last_t - s["t"] > 8.0:
                break
            is_outro = s["red"] > 0.22 or s["big_wm"]
            if is_outro or (s["dark"] and j == len(samples)):
                hit = hit or is_outro
                j -= 1
            else:
                break
        if hit and j < len(samples):
            t0 = samples[j]["t"]
            if j > 0:
                t0 = _refine_cut(video, fps, samples[j - 1]["t"], t0)
            if duration - t0 >= 0.5 and t0 > 1.0:
                trim_at = t0
                log(f"  phát hiện đoạn outro Xiaohongshu từ {t0:.1f}s, sẽ cắt bỏ")

    # ---- chốt các track ----
    final = []
    for tr in tracks:
        n_obs = len(tr["obs"])
        if tr["wm"]:
            if tr["red_only"] and n_obs < 3:
                continue  # khối đỏ thoáng qua, có thể là đồ vật màu đỏ
        elif n_obs < 2 and max(o[4] for o in tr["obs"]) < 0.6:
            continue
        ts = [o[0] for o in tr["obs"]]
        ext = dt * (1.6 if tr["wm"] else 1.0)
        tr["t0"], tr["t1"] = max(0.0, ts[0] - ext), ts[-1] + ext
        if trim_at is not None and ts[0] >= trim_at - 1e-3:
            continue  # chữ/logo chỉ xuất hiện trong outro (đã cắt)
        c = Counter(tr["texts"])
        top = max(c.values())
        tr["text"] = max((t for t, n in c.items() if n == top), key=len)
        boxes = np.array([o[1] for o in tr["obs"]])
        tr["ref"] = np.median(boxes, axis=0)
        tr["line_h"] = float(np.median([o[2] for o in tr["obs"]]))
        tr["n"] = int(round(np.median([o[3] for o in tr["obs"]])))
        cx = (boxes[:, 0] + boxes[:, 2]) / 2
        cy = (boxes[:, 1] + boxes[:, 3]) / 2
        tr["static"] = bool(np.ptp(cx) < 0.3 * tr["line_h"] and np.ptp(cy) < 0.3 * tr["line_h"])
        if not tr["wm"]:
            tr["kind"], tr["score"], tr["why"] = classify_text(tr, W, H)
        final.append(tr)

    _unify_kinds(final)
    _absorb_overlaps(final)

    regions = []
    for part in (opts.manual_regions or "").split(";"):
        nums = [float(v) for v in re.findall(r"[-+]?\d*\.?\d+", part)]
        if len(nums) == 4:
            regions.append((nums[0] * W, nums[1] * H, nums[2] * W, nums[3] * H))

    n_wm = sum(1 for t in final if t["wm"])
    log(f"  {len(final) - n_wm} đoạn chữ Trung, {n_wm} vị trí logo/watermark Xiaohongshu")
    from .utils import probe_video
    pv = probe_video(video)
    return {"fps": fps, "W": W, "H": H, "nframes": nframes, "duration": duration, "tracks": final,
            "regions": regions, "trim_at": trim_at, "fps_str": pv.get("fps_str"), "color": pv.get("color", "bt709")}


def classify_text(tr, W, H):
    """Chữ đồ hoạ chèn lên video (tiêu đề, phụ đề) hay chữ có sẵn trong cảnh (trên thiết bị, dụng cụ, bao bì)?

    Trả về ("overlay" | "scene", điểm, lý do). Điểm >= 2 -> chữ chèn.
    """
    s, why = 0, []
    st = tr.get("style", {})
    rel_h = tr["line_h"] / H                                   # cỡ chữ so với chiều cao khung hình
    bx = tr["ref"]
    bw = bx[2] - bx[0]
    cx = (bx[0] + bx[2]) / 2 / W
    cy = (bx[1] + bx[3]) / 2 / H
    ang = float(np.median(tr.get("angles") or [0.0]))
    conf = float(np.mean([o[4] for o in tr["obs"]]))
    n_cjk = len(CJK.findall(tr["text"]))

    def add(v, reason):
        nonlocal s
        s += v
        why.append(f"{reason} ({v:+d})")

    if rel_h >= 0.03:
        add(2, "chữ to")
    elif rel_h >= 0.02:
        add(1, "chữ vừa")
    elif rel_h < 0.014:
        add(-2, "chữ rất nhỏ")
    if ang > 4:
        add(-5, f"chữ nghiêng {ang:.0f}° theo đồ vật")
    elif ang > 2:
        add(-1, f"chữ hơi nghiêng {ang:.0f}°")
    if conf >= 0.9:
        add(1, "nét chữ rõ")
    elif conf < 0.7:
        add(-1, "chữ mờ")
    if st.get("fg_std", 99) < 28:
        add(1, "màu chữ đồng đều")
    elif st.get("fg_std", 0) > 50:
        add(-1, "màu chữ loang")
    if st.get("contrast", 255) < 60 and st.get("bg_std", 0) > 40:
        add(-1, "nền nhiều hoa văn")
    if abs(cx - 0.5) < 0.12 and bw > 0.3 * W:
        add(2, "căn giữa, dòng dài")
    elif abs(cx - 0.5) < 0.12:
        add(1, "căn giữa")
    if cy < 0.3 or cy > 0.65:
        add(1, "nằm ở dải tiêu đề/phụ đề")
    if not tr["static"]:
        add(-1, "di chuyển theo cảnh")
    if n_cjk >= 5:
        add(1, "cụm câu dài")
    elif n_cjk <= 2:
        add(-1, "chỉ vài chữ (nhãn, tên hãng)")
    return ("overlay" if s >= 2 else "scene"), s, why


def _unify_kinds(tracks):
    """Cùng một nội dung chữ xuất hiện nhiều lần -> xử lý giống nhau (lấy điểm cao nhất)."""
    norm = lambda t: re.sub(r"[\s\W_]+", "", t)  # noqa: E731
    best = {}
    for tr in tracks:
        if not tr["wm"]:
            k = norm(tr["text"])
            best[k] = max(best.get(k, -99), tr["score"])
    for tr in tracks:
        if not tr["wm"]:
            sc = best[norm(tr["text"])]
            if sc != tr["score"]:
                tr["why"] = tr["why"] + [f"cùng chữ ở đoạn khác được {sc:+d} điểm"]
                tr["score"] = sc
            tr["kind"] = "overlay" if tr["score"] >= 2 else "scene"


def _absorb_overlaps(tracks):
    """Khối chữ nhỏ nằm chồng lên khối lớn cùng thời điểm -> chỉ xoá, không vẽ chữ riêng (tránh đè nhau)."""
    txt = [t for t in tracks if not t["wm"]]
    area = lambda r: max(1.0, (r[2] - r[0]) * (r[3] - r[1]))  # noqa: E731
    for i, a in enumerate(txt):
        for b in txt[i + 1:]:
            t_ov = min(a["t1"], b["t1"]) - max(a["t0"], b["t0"])
            if t_ov <= 0.3 * min(a["t1"] - a["t0"], b["t1"] - b["t0"]):
                continue
            A, B = a["ref"], b["ref"]
            inter = max(0, min(A[2], B[2]) - max(A[0], B[0])) * max(0, min(A[3], B[3]) - max(A[1], B[1]))
            small, big = (a, b) if area(A) < area(B) else (b, a)
            if inter / area(small["ref"]) > 0.35:
                small["absorbed"] = True


def save_crops(video: Path, tracks, out_dir: Path):
    """Ảnh cắt từng đoạn chữ (để duyệt trên giao diện)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    res = {}
    for i, tr in enumerate(tracks):
        t, box = tr["obs"][len(tr["obs"]) // 2][:2]
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * fps))
        ok, fr = cap.read()
        if not ok:
            continue
        H, W = fr.shape[:2]
        p = int(tr["line_h"] * 0.6)
        x1, y1 = max(0, int(box[0]) - p), max(0, int(box[1]) - p)
        x2, y2 = min(W, int(box[2]) + p), min(H, int(box[3]) + p)
        crop = fr[y1:y2, x1:x2]
        if crop.size == 0:
            continue
        sc = min(1.0, 420 / crop.shape[1], 160 / crop.shape[0])
        crop = cv2.resize(crop, (max(1, int(crop.shape[1] * sc)), max(1, int(crop.shape[0] * sc))))
        name = f"crops/c{i}.jpg"
        cv2.imwrite(str(out_dir / f"c{i}.jpg"), crop, [cv2.IMWRITE_JPEG_QUALITY, 85])
        res[i] = name
    cap.release()
    return res


def save_debug(video: Path, info, out_dir: Path):
    cap = cv2.VideoCapture(str(video))
    fps = info["fps"]
    end = info["trim_at"] or info["duration"]
    paths = []
    for q in (0.15, 0.5, 0.85):
        tq = q * end
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(tq * fps))
        ok, fr = cap.read()
        if not ok:
            continue
        for tr in info["tracks"]:
            if tr["t0"] <= tq < tr["t1"]:
                b = box_at(tr, tq)
                # đỏ = logo đã xoá · xanh lá = chữ được dịch · vàng = chữ trên đồ vật, giữ nguyên
                col = (0, 0, 255) if tr["wm"] else ((0, 200, 255) if tr.get("skip") else (0, 220, 0))
                cv2.rectangle(fr, (int(b[0]), int(b[1])), (int(b[2]), int(b[3])), col, 3)
        for r in info["regions"]:
            cv2.rectangle(fr, (int(r[0]), int(r[1])), (int(r[2]), int(r[3])), (255, 0, 255), 3)
        sc = min(1.0, 720 / max(fr.shape[:2]))
        fr = cv2.resize(fr, (int(fr.shape[1] * sc), int(fr.shape[0] * sc)))
        p = out_dir / f"debug_{int(q * 100)}.jpg"
        cv2.imwrite(str(p), fr, [cv2.IMWRITE_JPEG_QUALITY, 85])
        paths.append(p.name)
    cap.release()
    return paths


# ======================= Xoá =======================
def cover(frame, box, style, mode, line_h, pad_ratio=0.25):
    H, W = frame.shape[:2]
    p = max(3, int(line_h * pad_ratio))
    x1, y1 = max(0, int(box[0]) - p), max(0, int(box[1]) - p)
    x2, y2 = min(W, int(box[2]) + p), min(H, int(box[3]) + p)
    if x2 <= x1 or y2 <= y1:
        return
    if mode == "solid":
        frame[y1:y2, x1:x2] = style["bg"]
        return
    m = max(6, int(line_h * 0.3))
    cx1, cy1, cx2, cy2 = max(0, x1 - m), max(0, y1 - m), min(W, x2 + m), min(H, y2 + m)
    roi = frame[cy1:cy2, cx1:cx2]
    mask = np.zeros(roi.shape[:2], np.uint8)
    if mode == "mask":
        inner = frame[y1:y2, x1:x2].astype(np.int16)
        dt_ = np.abs(inner - np.array(style["color"], np.int16)).sum(2)
        db = np.abs(inner - np.array(style["bg"], np.int16)).sum(2)
        mk = (dt_ < db).astype(np.uint8) * 255
        k = max(3, int(line_h * 0.2)) | 1
        mk = cv2.dilate(mk, np.ones((k, k), np.uint8))
        mask[y1 - cy1:y2 - cy1, x1 - cx1:x2 - cx1] = mk
    else:
        mask[y1 - cy1:y2 - cy1, x1 - cx1:x2 - cx1] = 255
    frame[cy1:cy2, cx1:cx2] = cv2.inpaint(roi, mask, 3, cv2.INPAINT_TELEA)


def cover_watermark(frame, box, line_h):
    """Logo XHS = khối đỏ có chữ + dòng ID: mở rộng vùng xoá rộng hơn chữ thường."""
    cover(frame, box, {"bg": (0, 0, 0), "color": (255, 255, 255)}, "box", line_h, pad_ratio=0.7)


# ======================= Vẽ chữ Việt =======================
def make_sprite(text, tr, W, opts):
    """Vẽ chữ Việt theo kiểu chữ + font người dùng chọn (textstyle)."""
    from . import textstyle
    bx = tr["ref"]
    box_w, box_h = bx[2] - bx[0], bx[3] - bx[1]
    if opts.text_preset == "original":
        b, g, r = tr["style"]["color"]
        fg = "#%02X%02X%02X" % (r, g, b)
        lum = 0.299 * r + 0.587 * g + 0.114 * b
        st = {"fg": opts.text_color or fg}
        if tr["style"]["contrast"] < 90 or opts.stroke_color:
            st["stroke"] = (opts.stroke_color or ("#000000" if lum > 128 else "#FFFFFF"), 0.08)
        if opts.bg_mode == "color" or (opts.bg_mode == "preset" and (opts.bg_color or opts.bg_opacity > 0)):
            st.update(bg="round", bg_color=opts.bg_color or "#000000",
                      bg_alpha=opts.bg_opacity if opts.bg_opacity >= 0 else 1.0)
    else:
        st = textstyle.resolve_style(opts.text_preset, opts.text_color, opts.bg_color, opts.stroke_color,
                                     opts.bg_opacity, opts.bg_mode)
    if opts.bg_mode == "none" and opts.text_preset == "original":
        st["bg"] = "none"
    has_bg = st.get("bg", "none") != "none"
    max_lines = max(2, tr["n"] + 1)
    if opts.fit_mode == "fit":
        # Vừa khung chữ gốc: khối chữ Việt (kể cả nền) nằm gọn trong vùng chữ Trung đã xoá,
        # chỉ được rộng/cao hơn một chút -> không che hình ảnh xung quanh.
        st.update(textstyle.COMPACT_PAD)
        size0 = max(8, int(tr["line_h"] * max(opts.font_scale, 0.9)))
        max_w = max(box_w * 1.12, min(W * 0.5, tr["line_h"] * 5))
        # 1) cố giữ đúng số dòng + chiều cao như chữ gốc (chữ nhỏ lại tối đa còn 60%)
        h1 = box_h * 1.35 + 2 * int(size0 * textstyle.COMPACT_PAD["pady"])
        font, size, lines = textstyle.fit_text(text, opts.font, size0, max_w, tr["n"], st, h1, min_scale=0.6)
        bw, bh = textstyle.block_size(lines, font, size, st)
        if len(lines) > tr["n"] or bh > h1 or bw > max_w * 1.02:
            # 2) không vừa thì cho thêm 1 dòng, vẫn giới hạn chiều cao
            max_h = max(box_h * 1.3, tr["line_h"] * 2.3)
            font, size, lines = textstyle.fit_text(text, opts.font, size0, max_w, max_lines, st, max_h,
                                                   min_scale=0.42)
        min_w = min_h = 0
    else:
        size0 = max(8, int(tr["line_h"] * opts.font_scale))
        max_w = min(W * 0.94, max(box_w * 1.8, W * (0.45 if has_bg else 0.3)))
        font, size, lines = textstyle.fit_text(text, opts.font, size0, max_w, max_lines, st)
        # có khung: khung luôn phủ kín vùng chữ gốc đã xoá
        min_w = min(W, box_w * 1.1) if has_bg else 0
        min_h = box_h * 1.15 if has_bg else 0
    img = textstyle.render_text(lines, font, size, st, min_w, min_h)
    arr = np.array(img)
    return arr[..., [2, 1, 0]].astype(np.float32), arr[..., 3:4].astype(np.float32) / 255.0


def sprite_rect(frame, spr, cx, cy):
    h, w = spr[1].shape[:2]
    H, W = frame.shape[:2]
    x = int(min(max(cx - w / 2, 0), max(0, W - w)))
    y = int(min(max(cy - h / 2, 0), max(0, H - h)))
    return (x, y, x + w, y + h)


def _rect_overlap(a, b):
    inter = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    small = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return inter / small if small > 0 else 0.0


def overlay(frame, spr, cx, cy):
    bgr, a = spr
    h, w = a.shape[:2]
    H, W = frame.shape[:2]
    x = int(min(max(cx - w / 2, 0), max(0, W - w)))
    y = int(min(max(cy - h / 2, 0), max(0, H - h)))
    x2, y2 = min(W, x + w), min(H, y + h)
    sa = a[:y2 - y, :x2 - x]
    sb = bgr[:y2 - y, :x2 - x]
    roi = frame[y:y2, x:x2].astype(np.float32)
    frame[y:y2, x:x2] = (roi * (1 - sa) + sb * sa).astype(np.uint8)


# ======================= Xuất video =======================
def scale_info(info, s):
    """Phóng to toàn bộ toạ độ chữ/logo theo hệ số s (dùng khi nâng độ phân giải video)."""
    W = int(round(info["W"] * s / 2)) * 2
    H = int(round(info["H"] * s / 2)) * 2
    s = W / info["W"]
    for tr in info["tracks"]:
        tr["ref"] = np.array(tr["ref"]) * s
        tr["line_h"] = tr["line_h"] * s
        tr["obs"] = [(t, [v * s for v in b], lh * s, n, c) for t, b, lh, n, c in tr["obs"]]
    info["regions"] = [tuple(v * s for v in r) for r in info["regions"]]
    info.update(W=W, H=H, scale=s, srcW=info.get("srcW", info["W"]), srcH=info.get("srcH", info["H"]))
    return info


SWS = "lanczos+accurate_rnd+full_chroma_int+full_chroma_inp+bitexact"


class FrameReader:
    """Giải mã khung hình bằng ffmpeg với chuẩn màu chỉ định rõ (chính xác hơn OpenCV, không lệch màu/độ sáng)."""

    def __init__(self, video, W, H, color="bt709", sharpen=False):
        self.W, self.H, self.size = W, H, W * H * 3
        mat = "bt709" if color == "bt709" else "bt601"
        # khi phóng to: ffmpeg dùng Lanczos rồi làm nét nhẹ
        extra = ",unsharp=5:5:0.6:5:5:0.0" if sharpen else ""
        self.p = subprocess.Popen(
            ["ffmpeg", "-loglevel", "error", "-i", str(video), "-map", "0:v:0", "-vsync", "passthrough",
             "-sws_flags", SWS, "-vf", f"scale={W}:{H}:in_color_matrix={mat}:out_range=pc{extra}",
             "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def read(self):
        b = self.p.stdout.read(self.size)
        if len(b) < self.size:
            return False, None
        return True, np.frombuffer(b, np.uint8).reshape(self.H, self.W, 3).copy()

    def release(self):
        try:
            self.p.stdout.close()
            self.p.kill()
            self.p.wait()
        except Exception:  # noqa: BLE001
            pass


def render(video: Path, audio: Path, info, opts, out: Path, log=print, signature=None):
    from .utils import AUDIO_ARGS, video_encode_args
    fps, W, H = info["fps"], info["W"], info["H"]
    scale = info.get("scale", 1.0)
    nframes = info["nframes"]
    end_t = info["trim_at"] or 1e9
    tracks = info["tracks"]
    log_path = out.with_suffix(".ffmpeg.log")
    with open(log_path, "w") as lg:
        proc = subprocess.Popen(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
             "-r", info.get("fps_str") or f"{fps}", "-i", "-", "-i", str(audio), "-map", "0:v", "-map", "1:a",
             # chuyển BGR -> YUV đúng chuẩn màu của video gốc (tránh lệch màu / mờ khi xử lý qua OpenCV)
             "-sws_flags", SWS,
             "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2,scale=out_color_matrix="
                    + ("bt709" if info.get("color", "bt709") == "bt709" else "bt601") + ":out_range=tv",
             *video_encode_args(opts.quality, info.get("color", "bt709")), *AUDIO_ARGS, "-shortest",
             str(out)],
            stdin=subprocess.PIPE, stderr=lg)
        cap = FrameReader(video, W, H, info.get("color", "bt709"), sharpen=scale != 1.0)
        idx = 0
        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                t = idx / fps
                if t >= end_t:
                    break
                act = [tr for tr in tracks if tr["t0"] <= t < tr["t1"] and not tr.get("skip")]
                boxes = [box_at(tr, t) for tr in act]
                for r in info["regions"]:
                    cover(frame, r, {"bg": (0, 0, 0), "color": (255, 255, 255)},
                          "solid" if opts.cover_mode == "solid" else "box", 20)
                for tr, bx in zip(act, boxes):
                    if tr["wm"]:
                        cover_watermark(frame, bx, tr["line_h"])
                    else:
                        cover(frame, bx, tr["style"], opts.cover_mode, tr["line_h"])
                placed = []
                draw = [(tr, bx) for tr, bx in zip(act, boxes)
                        if not tr["wm"] and tr.get("sprite") is not None and not tr.get("absorbed")]
                draw.sort(key=lambda p: -p[0]["sprite"][1].size)   # khung to vẽ trước, được ưu tiên
                for tr, bx in draw:
                    r = sprite_rect(frame, tr["sprite"], (bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2)
                    if any(_rect_overlap(r, q) > 0.25 for q in placed):
                        continue   # sẽ đè lên chữ khác -> bỏ qua
                    overlay(frame, tr["sprite"], (bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2)
                    placed.append(r)
                if signature is not None:
                    signature.draw(frame, t)
                proc.stdin.write(frame.tobytes())
                idx += 1
                if nframes and idx % max(1, nframes // 20) == 0:
                    log(f"  xuất video {min(100, round(100 * idx / nframes))}%", progress=idx / nframes)
        finally:
            cap.release()
            proc.stdin.close()
            proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(log_path.read_text()[-1500:])
