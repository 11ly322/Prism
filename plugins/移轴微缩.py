# -*- coding: utf-8 -*-
"""移轴微缩：横向清晰带 + 上下渐进虚化，做出微缩模型感。"""
PLUGIN_NAME = "移轴微缩"
PLUGIN_DESC = "横向清晰带 + 上下渐进虚化，旅游照变玩具模型"
PLUGIN_VERSION = "1.0"
PLUGIN_AUTHOR = "Prism"

from PIL import Image, ImageFilter, ImageEnhance

PLUGIN = {"id": "tilt_shift", "name": PLUGIN_NAME, "version": PLUGIN_VERSION,
          "api": 2, "author": PLUGIN_AUTHOR,
          "description": {"zh": "横向清晰带 + 上下渐进虚化，做微缩模型效果", "en": "Horizontal focus band with progressive blur above and below, for a miniature look", "ja": "横方向のピント帯と上下のぼかしでミニチュア風に"},
          "network": False, "writes_files": False}

PARAMS = [
    {"key": "band", "label": {"zh": "清晰带", "en": "Focus band", "ja": "ピント帯"}, "type": "slider",
     "min": 4, "max": 80, "default": 26, "step": 2},
    {"key": "blur", "label": {"zh": "虚化强度", "en": "Blur", "ja": "ぼかし"}, "type": "slider",
     "min": 1, "max": 30, "default": 12, "step": 1},
    {"key": "sat", "label": {"zh": "饱和提升", "en": "Saturation", "ja": "彩度"}, "type": "slider",
     "min": 0, "max": 100, "default": 45, "step": 5},
    {"key": "pos", "label": {"zh": "清晰带位置", "en": "Band position", "ja": "ピント帯の位置"}, "type": "select",
     "options": ["居中", "偏上", "偏下"], "default": "居中"},
]


def run(img, **params):
    p = params or {}
    alpha = None
    if img.mode == "RGBA":
        alpha = img.split()[3]
    rgb = img.convert("RGB")

    w, h = rgb.size
    scale = 1.0
    if max(w, h) > 2048:
        scale = 2048.0 / max(w, h)
        work = rgb.resize((int(w * scale), int(h * scale)), Image.BILINEAR)
    else:
        work = rgb
    ww, wh = work.size

    blur = float(p.get("blur", 12))
    blurred = work.filter(ImageFilter.GaussianBlur(max(0.5, blur * scale or blur)))
    sat = float(p.get("sat", 45)) / 100.0
    if sat > 0:
        sharp = ImageEnhance.Color(work).enhance(1.0 + 0.9 * sat)
    else:
        sharp = work

    band = max(4.0, min(80.0, float(p.get("band", 26)))) / 100.0
    pos = str(p.get("pos", "居中"))
    center = {"居中": 0.5, "偏上": 0.30, "偏下": 0.70}.get(pos, 0.5)
    half = band / 2.0

    # 纵向遮罩：清晰带内 255，向外线性衰减到 0
    mask = Image.new("L", (ww, wh), 0)
    px = mask.load()
    for y in range(wh):
        fy = y / float(max(1, wh - 1))
        d = abs(fy - center)
        if d <= half:
            v = 255
        elif d >= half * 2.2:
            v = 0
        else:
            v = int(255 * (1.0 - (d - half) / (half * 1.2)))
        for x in range(ww):
            px[x, y] = v

    out = Image.composite(sharp, blurred, mask)
    if scale != 1.0:
        out = out.resize((w, h), Image.BICUBIC)
    if alpha is not None:
        out = out.convert("RGBA")
        out.putalpha(alpha)
    return out
