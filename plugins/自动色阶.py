# -*- coding: utf-8 -*-
PLUGIN_NAME = "自动色阶"
PLUGIN_DESC = {"zh": "把直方图拉满，去掉灰蒙蒙的感觉", "en": "Stretches the histogram to remove a washed-out look", "ja": "ヒストグラムを引き伸ばして霞んだ印象を解消"}
PLUGIN_VERSION = "2.0"
PLUGIN_AUTHOR = "Prism"

from PIL import Image

PLUGIN = {"id": "autolevel", "name": PLUGIN_NAME, "version": PLUGIN_VERSION,
          "api": 2, "author": PLUGIN_AUTHOR}

PARAMS = [
    {"key": "cutoff", "label": {"zh": "裁切比例", "en": "Cutoff", "ja": "カット率"}, "min": 0, "max": 5,
     "default": 0.4, "step": 0.1},
    {"key": "strength", "label": {"zh": "强度", "en": "Strength", "ja": "強さ"}, "min": 0, "max": 100,
     "default": 100, "step": 5},
]


def run(img, **params):
    from PIL import ImageOps
    p = params or {}
    rgb = img.convert("RGB")
    cut = float(p.get("cutoff", 0.4))
    full = ImageOps.autocontrast(rgb, cutoff=(cut, cut))
    k = float(p.get("strength", 100)) / 100.0
    if k >= 1.0:
        return full
    if k <= 0:
        return rgb
    return Image.blend(rgb, full, k)
