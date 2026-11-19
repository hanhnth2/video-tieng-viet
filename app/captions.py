"""Tạo câu hook, caption và hashtag cho TikTok / Facebook — hợp nội dung video, thu hút, an toàn.

- Có ANTHROPIC_API_KEY: Claude đọc tiêu đề + chữ trên hình + lời thoại, viết hook theo nhiều công thức viral.
- Không có: bộ mẫu theo chủ đề (ngách) + điền thông tin rút ra từ video (lợi ích, con số, chủ thể).
- Mọi kết quả qua 2 lớp an toàn:
    1) tự sửa mềm từ ngữ rủi ro ("100%", "cam kết", "chữa khỏi"...)
    2) kiểm tra lại, câu còn rủi ro cao bị loại; tuyên bố nhạy cảm (thay đổi cơ thể...) được cảnh báo.
Lưu ý: không ai có thể "đảm bảo lên xu hướng"; công cụ chỉ tối ưu theo các nguyên tắc nội dung ngắn phổ biến.
"""
from __future__ import annotations

import json
import random
import re

from . import config

# ---------------- An toàn nội dung ----------------
# (mẫu, lý do, mức) — mức "block": loại bỏ / sửa; "warn": giữ nhưng cảnh báo
RISKY = [
    (r"100\s*%|cam kết|bảo đảm|đảm bảo|chắc chắn (sẽ|hiệu quả)|hiệu quả tức thì|vĩnh viễn", "Hứa hẹn kết quả tuyệt đối", "block"),
    (r"chữa (khỏi|bệnh|dứt điểm)|trị (dứt điểm|tận gốc)|thần dược|khỏi hẳn|đặc trị", "Tuyên bố chữa bệnh", "block"),
    (r"giảm \d+\s*kg|cấp tốc|thần tốc|siêu tốc", "Hứa hẹn thay đổi cơ thể nhanh", "block"),
    (r"(like|thả tim|share|chia sẻ|tag|bình luận|comment|follow)\s+(ngay\s+)?(để|nếu|cho|khi)", "Câu kéo tương tác (engagement bait)", "block"),
    (r"inbox|ib ngay|nhắn tin ngay|zalo|số điện thoại|sđt|link ở bio|link trong bio", "Kéo người xem ra ngoài nền tảng", "block"),
    (r"rẻ nhất|tốt nhất|số 1|duy nhất|đỉnh nhất", "So sánh tuyệt đối khó chứng minh", "block"),
    (r"cá cược|nhà cái|casino|vay tiền|kiếm tiền dễ|làm giàu nhanh", "Tài chính/cờ bạc bị hạn chế", "block"),
    (r"sốc|kinh hoàng|không thể tin nổi|bí mật động trời", "Giật tít gây hiểu lầm", "block"),
    (r"tăng chiều cao|giảm cân|giảm mỡ|eo thon|chân thon|ngực|vòng 1|trắng da|nám|mụn", "Nội dung về ngoại hình/cơ thể: tránh hứa hẹn kết quả, nên dùng 'hỗ trợ', 'giúp cảm thấy'", "warn"),
]
SOFTEN = [  # sửa mềm tự động
    (r"\s*100\s*%", ""), (r"\b(cam kết|bảo đảm|đảm bảo)\s*", ""), (r"chắc chắn sẽ", "có thể"),
    (r"hiệu quả tức thì", "dễ áp dụng"), (r"vĩnh viễn", "lâu dài"),
    (r"chữa (khỏi|dứt điểm)|trị (dứt điểm|tận gốc)|đặc trị", "hỗ trợ cải thiện"), (r"thần dược", "bí quyết"),
    (r"\s*(cấp tốc|thần tốc|siêu tốc)", ""), (r"giảm \d+\s*kg", "gọn dáng hơn"),
    (r"rẻ nhất", "giá tốt"), (r"tốt nhất|đỉnh nhất|số 1", "đáng thử"), (r"\bduy nhất\b", "đặc biệt"),
    (r"\bsốc\b", "bất ngờ"), (r"kinh hoàng|không thể tin nổi", "bất ngờ"),
]
SPAM_TAGS = {"#fyp", "#foryou", "#foryoupage", "#xyzbca", "#viral", "#trending", "#xh", "#fypシ"}


def soften(text: str) -> str:
    out = text or ""
    for pat, rep in SOFTEN:
        out = re.sub(pat, rep, out, flags=re.I)
    return re.sub(r"\s{2,}", " ", out).strip(" ,")


def check_compliance(text: str, level=None) -> list[str]:
    out = []
    low = (text or "").lower()
    for pat, why, lv in RISKY:
        if level and lv != level:
            continue
        m = re.search(pat, low)
        if m:
            out.append(f"{why}: “{m.group(0)}”")
    return out


# ---------------- Chủ đề (ngách) ----------------
NICHES = {
    "tập luyện": {
        "kw": ["tập", "yoga", "bài tập", "giãn", "động tác", "cơ", "plank", "squat", "cột sống", "khung chậu", "dáng", "gym", "thể dục"],
        "sub": "bài tập này", "act": "tập", "pain": ["ngồi nhiều, hay mỏi lưng", "thấy dáng đứng chưa thẳng", "bị căng cứng bắp chân"],
        "mistake": "tập sai tư thế", "tags": ["#yoga", "#taptainha", "#baitap", "#suckhoe", "#giandaco", "#fitness"]},
    "làm đẹp": {
        "kw": ["kem", "da", "son", "serum", "mỹ phẩm", "dưỡng", "makeup", "trang điểm", "mặt nạ", "tóc", "skincare"],
        "sub": "cách chăm da này", "act": "áp dụng", "pain": ["bị da khô ráp", "bị lớp nền mốc", "khổ vì tóc xơ rối"],
        "mistake": "bôi kem sai thứ tự", "tags": ["#lamdep", "#skincare", "#reviewmypham", "#chamsocda", "#makeup"]},
    "gia dụng": {
        "kw": ["nồi", "bếp", "chảo", "máy", "dụng cụ", "nhà bếp", "lau", "dọn", "tủ", "kệ", "gia dụng", "nhà cửa"],
        "sub": "món đồ này", "act": "dùng", "pain": ["mệt vì nhà bếp bừa bộn", "mất cả giờ dọn dẹp", "thiếu chỗ cất đồ"],
        "mistake": "cất đồ sai cách", "tags": ["#dogiadung", "#meovat", "#nhacuaxinh", "#tienich", "#reviewdogiadung"]},
    "công nghệ": {
        "kw": ["điện thoại", "tai nghe", "sạc", "laptop", "camera", "loa", "đồng hồ", "công nghệ", "app", "pin"],
        "sub": "món công nghệ này", "act": "dùng", "pain": ["khổ vì điện thoại hay hết pin", "bực vì dây sạc rối tung", "dùng máy chạy chậm"],
        "mistake": "sạc pin sai cách", "tags": ["#congnghe", "#reviewcongnghe", "#tech", "#phukiencongnghe", "#meocongnghe"]},
    "thời trang": {
        "kw": ["áo", "quần", "váy", "giày", "túi", "phối đồ", "outfit", "thời trang", "mũ"],
        "sub": "cách phối đồ này", "act": "phối", "pain": ["mặc mãi thấy chưa ưng", "khó chọn đồ hợp dáng", "có tủ đầy mà vẫn thiếu đồ"],
        "mistake": "phối màu lệch tông", "tags": ["#thoitrang", "#outfit", "#phoido", "#ootd", "#fashion"]},
    "ẩm thực": {
        "kw": ["ăn", "món", "nấu", "ngon", "bánh", "trà", "cà phê", "đồ ăn", "công thức", "nhà hàng"],
        "sub": "món này", "act": "nấu", "pain": ["không biết hôm nay ăn gì", "nấu mãi chưa ngon", "bận không có thời gian nấu"],
        "mistake": "nêm nếm sai thứ tự", "tags": ["#amthuc", "#monngon", "#nauan", "#reviewdoan", "#anngon"]},
    "du lịch": {
        "kw": ["du lịch", "khách sạn", "bãi biển", "check in", "phố", "núi", "chuyến đi"],
        "sub": "địa điểm này", "act": "ghé", "pain": ["sợ đi chơi chỗ đông", "chưa biết cuối tuần đi đâu", "lo bị chặt chém khi du lịch"],
        "mistake": "đặt phòng sát ngày", "tags": ["#dulich", "#checkin", "#travel", "#reviewdulich", "#xachbalodi"]},
    "mẹ và bé": {
        "kw": ["bé", "trẻ em", "mẹ", "em bé", "đồ chơi", "con nhỏ"],
        "sub": "mẹo nuôi con này", "act": "áp dụng", "pain": ["đau đầu vì bé lười ăn", "mệt vì bé khó ngủ", "khổ vì đồ chơi bừa bộn"],
        "mistake": "cho bé chơi sai cách", "tags": ["#mevabe", "#nuoicon", "#dochoitreem", "#embe", "#meohay"]},
    "thú cưng": {
        "kw": ["mèo", "chó", "cún", "thú cưng", "pet"],
        "sub": "mẹo chăm boss này", "act": "thử", "pain": ["đau đầu vì boss cào phá", "khổ vì lông rụng khắp nhà", "lo vì boss biếng ăn"],
        "mistake": "cho boss ăn sai cách", "tags": ["#thucung", "#meo", "#cho", "#pet", "#boss"]},
}
GENERIC = {"sub": "điều này", "act": "thử", "pain": ["mất nhiều thời gian", "làm mãi chưa được"], "mistake": "làm sai cách",
           "tags": ["#review", "#chiase", "#trainghiem", "#meohay"]}
BASE_TIKTOK = ["#xuhuong", "#tiktokvietnam", "#learnontiktok"]
BASE_FB = ["#reels", "#xuhuong"]

# công thức hook: (loại, mẫu)
FORMULAS = [
    ("Tò mò", ["Chỉ {num} mỗi ngày, cơ thể bạn sẽ khác thế này", "Ít ai biết {sub} lại {benefit_v} dễ đến vậy",
               "Làm thử {sub} và đây là kết quả thật"]),
    ("Nỗi lo", ["Nếu bạn đang {pain}, thử ngay {sub}", "Ai đang {pain} nhất định phải xem"]),
    ("POV", ["POV: Bạn tìm được {sub} {benefit_v} ngay tại nhà", "POV: {num} mỗi ngày và thói quen mới của bạn"]),
    ("Sai lầm", ["Đừng {mistake} nữa, làm thế này mới đúng", "Rất nhiều người mới {mistake}, bạn có đang vậy không?"]),
    ("Con số", ["{steps} bước để {benefit_n}, ai cũng làm được", "Chỉ cần {num} mỗi ngày để {benefit_n}"]),
    ("Câu hỏi", ["Bạn đã {act} {sub} đúng cách chưa?", "Vì sao {sub} được nhiều người {act} đến vậy?"]),
    ("Thử thách", ["Thử thách 7 ngày với {sub}, bạn dám không?", "Cùng mình {act} {sub} trong 7 ngày nhé"]),
    ("Lưu lại", ["Lưu lại để {act} mỗi ngày nhé", "Video này đáng lưu nếu bạn muốn {benefit_n}"]),
]


def _clean_tags(tags, limit):
    seen, out = set(), []
    for t in tags:
        t = "#" + re.sub(r"[^\w]", "", str(t).lstrip("#").replace(" ", "")).lower()
        if len(t) < 3 or t in seen or t in SPAM_TAGS:
            continue
        seen.add(t)
        out.append(t)
    return out[:limit]


def _overlay(text):
    """Bản in lên video: giữ nguyên câu nếu ngắn, dài thì cắt ở dấu phẩy (không cắt giữa câu)."""
    if len(text.split()) <= 12:
        return text
    head = re.split(r"[,:;]", text)[0].strip()
    return head if 3 <= len(head.split()) <= 12 else text


def detect_niche(text):
    low = text.lower()
    best, score = None, 0
    for name, d in NICHES.items():
        s = sum(low.count(k) for k in d["kw"])
        if s > score:
            best, score = name, s
    return best


def _facts(texts):
    """Rút lợi ích, con số, số bước từ chữ trong video."""
    joined = " ".join(texts)
    low = joined.lower()
    # ưu tiên lợi ích không chứa tuyên bố nhạy cảm về cơ thể
    cands = []
    for t in texts:  # xét từng câu riêng để cụm lợi ích không dính sang câu khác
        tl = (t or "").lower()
        cands += [m.group(1) for m in re.finditer(r"(?:giúp|để)\s+([^,.;:!?]{4,60})", tl)]
        cands += [m.group(1) for m in re.finditer(r"(kéo giãn[^,.;:!?]{2,40}|thư giãn[^,.;:!?]{0,40})", tl)]
    # cắt ở từ nối, tối đa 7 từ
    cands = [" ".join(re.split(r"\s(?:mỗi|trong|sau|khi|nhưng|rồi|thì)\s", c)[0].split()[:7]).strip() for c in cands]
    cands = [c for c in cands if len(c.split()) >= 2]
    safe = [c for c in cands if not check_compliance(c)]
    benefit = (safe or cands or [""])[0]
    num = ""
    m = re.search(r"(\d+)\s*(phút|giây|ngày|tuần)", low)
    if m:
        num = f"{m.group(1)} {m.group(2)}"
    steps = ""
    m = re.search(r"(\d+)\s*(bước|cách|động tác|mẹo|bài)", low)
    if m:
        steps = m.group(1)
    return benefit, num, steps


def _fallback(vi_lines, screen, title_vi, tone, trending):
    texts = [title_vi] + screen + vi_lines
    niche = detect_niche(" ".join(texts))
    d = NICHES.get(niche, GENERIC)
    benefit, num, steps = _facts(texts)
    benefit = soften(benefit)
    slots = {
        "sub": d["sub"], "act": d["act"], "mistake": d["mistake"], "pain": random.choice(d["pain"]),
        "num": num, "steps": steps,
        "benefit_v": f"giúp {benefit}" if benefit else "hiệu quả",
        "benefit_n": benefit or f"{d['act']} đúng cách",
    }
    rnd = random.Random()
    hooks = []
    for kind, tpls in rnd.sample(FORMULAS, len(FORMULAS)):
        # bỏ mẫu cần thông tin video không có (không bịa con số / lợi ích)
        ok = [t for t in tpls if not ("{num}" in t and not num) and not ("{steps}" in t and not steps)
              and not ("{benefit" in t and not benefit)]
        if not ok:
            continue
        tpl = rnd.choice(ok)
        text = soften(tpl.format(**slots))
        text = text[0].upper() + text[1:]
        hooks.append({"text": text, "type": kind, "overlay": _overlay(text)})
        if len(hooks) == 6:
            break
    summary_src = [l.strip(" .") for l in (vi_lines + screen[:1]) if l and not check_compliance(l)]
    summary = ". ".join(summary_src[:2])[:180]
    tt_tags = _clean_tags(trending + d["tags"][:4] + BASE_TIKTOK, 6)
    fb_tags = _clean_tags(trending[:1] + d["tags"][:2] + BASE_FB, 4)
    q = {"tập luyện": "Bạn tập bài này được mấy phút rồi?", "làm đẹp": "Bạn đang dùng cách nào cho da mình?",
         "ẩm thực": "Bạn muốn mình làm món gì tiếp theo?"}.get(niche, "Bạn thấy sao về cách này?")
    return {
        "hooks": hooks,
        "tiktok": {"caption": f"{hooks[0]['text']} 👇 {(summary + '. ') if summary else ''}{q}".strip(), "hashtags": tt_tags},
        "facebook": {"caption": f"{hooks[1]['text']}\n{summary + '.' if summary else ''}\n{q}".strip(), "hashtags": fb_tags},
        "topic": niche or "chung",
        "engine": "mẫu có sẵn (thêm ANTHROPIC_API_KEY để viết sát nội dung hơn)",
    }


PROMPT = """Bạn là chuyên gia sáng tạo video ngắn top đầu thị trường Việt Nam (TikTok, Facebook Reels), hiểu thuật toán đề xuất và
Nguyên tắc cộng đồng TikTok, Tiêu chuẩn cộng đồng Meta, chính sách nội dung có thương hiệu.

THÔNG TIN VIDEO (đã dịch sang tiếng Việt)
- Tiêu đề gốc: {title}
- Chủ đề dự đoán: {niche}
- Chữ trên hình: {screen}
- Lời thoại: {speech}
- Giọng văn mong muốn: {tone}
- Hashtag xu hướng người dùng cung cấp (ưu tiên dùng nếu hợp nội dung): {trending}

YÊU CẦU
1. 6 câu hook, mỗi câu dùng MỘT công thức khác nhau trong: Tò mò, Nỗi lo, POV, Sai lầm, Con số, Câu hỏi, Thử thách, Lưu lại, Trước–sau.
   - Bám SÁT nội dung thật của video (nhắc đúng động tác/sản phẩm/lợi ích có trong video), không bịa thông tin.
   - Tối đa 12 từ, đọc tự nhiên như người Việt nói, tạo khoảng trống tò mò khiến người xem muốn xem tiếp.
   - Kèm "overlay": bản rút gọn ≤ 8 từ để in lên 3 giây đầu video.
   - Kèm "why": 1 câu ngắn giải thích vì sao hook này giữ chân người xem.
2. Caption TikTok: 1–2 câu, chứa 1–2 từ khoá mà người dùng hay TÌM KIẾM về chủ đề này (SEO TikTok), có thể 1–2 emoji,
   kết thúc bằng câu hỏi mở về trải nghiệm thật của người xem.
3. 5–6 hashtag TikTok: 1–2 hashtag chủ đề lớn + 2–3 hashtag ngách đúng nội dung + #xuhuong. Viết liền, không dấu.
4. Caption Facebook: 2–3 câu gần gũi, nêu giá trị người xem nhận được, câu hỏi mở cuối bài. 3–4 hashtag Facebook.

BẮT BUỘC TUÂN THỦ (nếu vi phạm, viết lại):
- Không hứa hẹn tuyệt đối: 100%, cam kết, đảm bảo, chắc chắn, hiệu quả tức thì, vĩnh viễn, tốt nhất, rẻ nhất, số 1, duy nhất.
- Nội dung sức khoẻ/ngoại hình/cơ thể: không hứa kết quả (tăng chiều cao, giảm cân, giảm mỡ, trắng da...), dùng "hỗ trợ", "giúp cảm thấy",
  không chê bai ngoại hình, không gây tự ti cơ thể.
- Không chữa bệnh, không lời khuyên y tế/tài chính gây hiểu lầm.
- Không câu kéo tương tác ("like/share/tag/bình luận/follow để..."), không giật tít sai sự thật, không gây sợ hãi.
- Không kêu gọi inbox, Zalo, số điện thoại, link ngoài; không nhắc nền tảng khác.
- Không hashtag rỗng nghĩa/spam (#fyp #foryou #viral #xyzbca).
- Thêm vào "notes" lời nhắc cần thiết (ghi nguồn nếu video không tự quay, gắn nhãn quảng cáo nếu là nội dung có tài trợ...).

Trả về DUY NHẤT JSON:
{{"hooks": [{{"text": "...", "type": "Tò mò", "overlay": "...", "why": "..."}}],
  "tiktok": {{"caption": "...", "hashtags": ["#..."]}},
  "facebook": {{"caption": "...", "hashtags": ["#..."]}},
  "topic": "chủ đề ngắn", "notes": ["..."]}}"""


def _claude(vi_lines, screen, title, niche, tone, trending):
    import anthropic
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    body = PROMPT.format(title=title or "(không có)", niche=niche or "chưa rõ", screen=" | ".join(screen[:20]) or "(không có)",
                         speech="\n".join(vi_lines[:80]) or "(không có lời thoại)", tone=tone or "gần gũi, tự nhiên",
                         trending=" ".join(trending) or "(không có)")
    msg = client.beta.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=16000,
        output_config={"effort": "medium"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{"role": "user", "content": body}],
    )
    if msg.stop_reason == "refusal":
        raise RuntimeError("Claude từ chối yêu cầu")
    raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    m = re.search(r"\{.*\}", raw, re.S)
    data = json.loads(m.group(0) if m else raw)
    data["engine"] = "Claude"
    return data


def generate(job_data: dict, tone: str = "", trending: str = "") -> dict:
    tr = job_data.get("transcript") or []
    vi_lines = [t["vi"] for t in tr if t.get("vi")]
    screen = [t["vi"] for t in job_data.get("screen_texts") or [] if t.get("vi")]
    trend_tags = re.findall(r"#?[\wÀ-ỹ]+", trending or "")
    title = job_data.get("title") or ""
    title_vi = title
    if title and re.search(r"[一-鿿]", title):
        try:
            from .speech import translate
            title_vi = translate([title])[0]
        except Exception:  # noqa: BLE001
            title_vi = ""
    niche = detect_niche(" ".join([title_vi] + screen + vi_lines))
    data = None
    if config.ANTHROPIC_API_KEY:
        try:
            data = _claude(vi_lines, screen, title_vi or title, niche, tone, trend_tags)
        except Exception as e:  # noqa: BLE001
            print("Claude lỗi khi tạo caption:", str(e)[:200])
    if data is None:
        data = _fallback(vi_lines, screen, title_vi, tone, trend_tags)

    # ---------- hậu kiểm an toàn ----------
    notes = list(data.get("notes") or [])
    hooks, removed = [], 0
    for h in data.get("hooks") or []:
        if isinstance(h, str):
            h = {"text": h, "type": "", "overlay": h}
        h["text"] = soften(h.get("text", ""))
        h["overlay"] = soften(h.get("overlay") or h["text"])
        if not h["text"] or check_compliance(h["text"], "block") or check_compliance(h["overlay"], "block"):
            removed += 1
            continue
        h["warn"] = check_compliance(h["text"], "warn")
        hooks.append(h)
    if removed:
        notes.append(f"Đã loại {removed} câu hook còn từ ngữ dễ vi phạm sau khi sửa.")
    data["hooks"] = hooks
    for plat, lim in (("tiktok", 6), ("facebook", 4)):
        blk = data.get(plat) or {}
        blk["caption"] = soften(blk.get("caption", ""))
        blk["hashtags"] = _clean_tags(blk.get("hashtags") or [], lim)
        for w in check_compliance(blk["caption"]):
            notes.append(f"{plat.capitalize()}: {w}")
        blk["full"] = (blk["caption"].strip() + "\n\n" + " ".join(blk["hashtags"])).strip()
        data[plat] = blk
    if any(h.get("warn") for h in hooks):
        notes.append("Video có nội dung về cơ thể/ngoại hình: không hứa kết quả, tránh hướng tới trẻ vị thành niên.")
    notes.append("Đăng giờ cao điểm (11h–13h, 19h–22h), gắn nhạc trong app để vào trend âm thanh.")
    notes.append("Nếu video không phải do bạn quay, hãy ghi nguồn hoặc xin phép tác giả để tránh bị báo cáo bản quyền.")
    notes.append("Hashtag xu hướng thay đổi hằng ngày: xem tại TikTok Creative Center (mục Trend → Hashtag, chọn Việt Nam) rồi dán vào ô 'Hashtag xu hướng'.")
    data["notes"] = list(dict.fromkeys(notes))
    data["niche"] = niche or "chung"
    return data
