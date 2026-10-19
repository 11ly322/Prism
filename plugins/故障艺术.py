# -*- coding: utf-8 -*-
"""故障艺术：通道错位 + 横向切片位移 + 扫描线。"""
PLUGIN_NAME = "故障艺术"
PLUGIN_DESC = "通道错位 + 切片位移 + 扫描线，赛博故障感"
PLUGIN_VERSION = "1.0"
PLUGIN_AUTHOR = "Prism"

import random
from PIL import Image, ImageChops, ImageDraw

PLUGIN = {"id": "glitch", "name": PLUGIN_NAME, "version": PLUGIN_VERSION,
          "api": 2, "author": PLUGIN_AUTHOR,
          "description": "RGB 通道错位与横向切片位移，做数字故障效果",
          "network": False, "writes_files": False}

PARAMS = [
    {"key": "shift", "label": "通道错位", "type": "slider",
     "min": 0, "max": 30, "default": 8, "step": 1},
    {"key": "slices", "label": "切片数量", "type": "slider",
     "min": 0, "max": 40, "default": 12, "step": 1},
    {"key": "seed", "label": "随机种子", "type": "slider",
     "min": 0, "max": 99, "default": 7, "step": 1},
    {"key": "scan", "label": "扫描线", "type": "checkbox", "default": True},
]


def run(img, **params):
    p = params or {}
    alpha = None
    if img.mode == "RGBA":
        alpha = img.split()[3]
    out = img.convert("RGB").copy()
    w, h = out.size

    shift = int(float(p.get("shift", 8)))
    if shift > 0:
        r, g, b = out.split()
        r = ImageChops.offset(r, shift, 0)
        b = ImageChops.offset(b, -shift, 0)
        out = Image.merge("RGB", (r, g, b))

    n = int(float(p.get("slices", 12)))
    if n > 0:
        rng = random.Random(int(float(p.get("seed", 7))))
        band = max(2, h // max(6, n * 2))
        for i in range(n):
            y0 = rng.randint(0, max(0, h - band - 1))
            piece = out.crop((0, y0, w, min(h, y0 + band)))
            dx = rng.randint(-max(4, w // 12), max(4, w // 12))
            out.paste(piece, (dx, y0))

    if bool(p.get("scan", True)):
        d = ImageDraw.Draw(out)
        step = max(2, h // 320)
        for y in range(0, h, step * 2):
            d.line([(0, y), (w, y)], fill=(0, 0, 0), width=1)

    if alpha is not None:
        out = out.convert("RGBA")
        out.putalpha(alpha)
    return out
