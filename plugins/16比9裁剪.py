# -*- coding: utf-8 -*-
PLUGIN_NAME = "16比9裁剪"
PLUGIN_DESC = {"zh": "按目标比例居中裁剪，做视频封面和 PPT 配图", "en": "Center-crops to a preset aspect ratio; useful for video covers and slide images", "ja": "指定比率で中央トリミング。動画サムネやスライド用画像に"}
PLUGIN_VERSION = "2.0"
PLUGIN_AUTHOR = "Prism"

from PIL import Image

PLUGIN = {"id": "crop169", "name": PLUGIN_NAME, "version": PLUGIN_VERSION,
          "api": 2, "author": PLUGIN_AUTHOR}

PARAMS = [
    {"key": "ratio", "label": {"zh": "目标比例", "en": "Aspect ratio", "ja": "アスペクト比"}, "type": "choice",
     "choices": ["16:9", "9:16", "4:3", "1:1"], "default": "16:9"},
    {"key": "align", "label": {"zh": "对齐", "en": "Align", "ja": "位置"}, "type": "choice",
     "choices": ["居中", "偏上", "偏下"], "default": "居中"},
]

_RATIOS = {"16:9": (16, 9), "9:16": (9, 16), "4:3": (4, 3), "1:1": (1, 1)}


def run(img, **params):
    p = params or {}
    rw, rh = _RATIOS.get(str(p.get("ratio", "16:9")), (16, 9))
    src = img.convert("RGBA") if img.mode == "RGBA" else img.convert("RGB")
    w, h = src.size
    target = rw / float(rh)
    cur = w / float(h)
    if cur > target:                      # 太宽：裁左右
        nw = max(1, int(round(h * target)))
        x0 = (w - nw) // 2
        box = (x0, 0, x0 + nw, h)
    else:                                 # 太高：裁上下
        nh = max(1, int(round(w / target)))
        align = str(p.get("align", "居中"))
        y0 = (h - nh) // 2
        if align == "偏上":
            y0 = 0
        elif align == "偏下":
            y0 = h - nh
        box = (0, y0, w, y0 + nh)
    return src.crop(box)
