# -*- coding: utf-8 -*-
PLUGIN_NAME = "黑白"
PLUGIN_DESC = "最简示例：一个插件最小可以多短。可调对比增强"
PLUGIN_VERSION = "2.0"
PLUGIN_AUTHOR = "Prism"

from PIL import Image

PLUGIN = {"id": "bw", "name": PLUGIN_NAME, "version": PLUGIN_VERSION,
          "api": 2, "author": PLUGIN_AUTHOR}

PARAMS = [
    {"key": "contrast", "label": "对比增强", "min": 0, "max": 100,
     "default": 20, "step": 5},
]


def run(img, **params):
    """最简示例：转灰度，再按强度拉一点对比。"""
    from PIL import ImageEnhance
    p = params or {}
    out = img.convert("L").convert("RGB")
    k = float(p.get("contrast", 20)) / 100.0
    if k > 0:
        out = ImageEnhance.Contrast(out).enhance(1.0 + 0.6 * k)
    return out
