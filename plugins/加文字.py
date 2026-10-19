# -*- coding: utf-8 -*-
PLUGIN_NAME = "加文字"
PLUGIN_DESC = "右下角加一行署名（带描边，深浅背景都看得清）"
PLUGIN_VERSION = "2.1"
PLUGIN_AUTHOR = "Prism"

from PIL import Image

PLUGIN = {"id": "watermark", "name": PLUGIN_NAME, "version": PLUGIN_VERSION,
          "api": 2, "author": PLUGIN_AUTHOR,
          "description": "右下角加一行署名，文字内容可自定义",
          "network": False, "writes_files": False}

PARAMS = [
    {"key": "text", "label": "署名文字", "type": "text", "default": "© Prism"},
    {"key": "size", "label": "字号占比", "min": 1, "max": 8,
     "default": 3.2, "step": 0.2},
    {"key": "margin", "label": "边距占比", "min": 0, "max": 8,
     "default": 2.0, "step": 0.5},
    {"key": "stroke", "label": "描边", "type": "checkbox", "default": True},
]


def _font(size):
    from PIL import ImageFont
    for name in ("msyh.ttc", "PingFang.ttc", "DejaVuSans.ttf",
                 "arial.ttf", "Arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def run(img, **params):
    from PIL import ImageDraw
    p = params or {}
    text = str(p.get("text") or "").strip() or "© Prism"
    out = img.convert("RGB").copy()
    w, h = out.size
    size = max(12, int(min(w, h) * float(p.get("size", 3.2)) / 100.0))
    margin = int(min(w, h) * float(p.get("margin", 2.0)) / 100.0)
    font = _font(size)
    draw = ImageDraw.Draw(out)
    try:
        box = draw.textbbox((0, 0), text, font=font)
        tw, th = box[2] - box[0], box[3] - box[1]
    except Exception:
        tw, th = size * len(text) // 2, size
    x = max(0, w - tw - margin)
    y = max(0, h - th - margin)
    if bool(p.get("stroke", True)):
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            draw.text((x + dx, y + dy), text, font=font, fill=(0, 0, 0))
    draw.text((x, y), text, font=font, fill=(255, 255, 255))
    return out
