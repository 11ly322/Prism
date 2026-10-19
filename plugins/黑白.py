# -*- coding: utf-8 -*-
PLUGIN_NAME = "黑白"
PLUGIN_DESC = {"zh": "最简示例：一个插件最小可以多短。可调对比增强", "en": "Minimal example: the shortest possible plugin. Adjustable contrast boost", "ja": "最小例：もっとも短いプラグイン。コントラスト強調を調整"}
PLUGIN_VERSION = "2.0"
PLUGIN_AUTHOR = "Prism"

from PIL import Image

PLUGIN = {"id": "bw", "name": PLUGIN_NAME, "version": PLUGIN_VERSION,
          "api": 2, "author": PLUGIN_AUTHOR}

PARAMS = [
    {"key": "contrast", "label": {"zh": "对比增强", "en": "Contrast boost", "ja": "コントラスト強調"}, "min": 0, "max": 100,
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
