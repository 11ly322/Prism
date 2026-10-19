# -*- coding: utf-8 -*-
"""丁达尔光：把亮部沿一个方向拉出光束，叠加回画面。"""
PLUGIN_NAME = "丁达尔光"
PLUGIN_DESC = "亮部沿指定方向拉出光束，逆光照片立刻有氛围"
PLUGIN_VERSION = "1.0"
PLUGIN_AUTHOR = "Prism"

import math
from PIL import Image, ImageChops, ImageEnhance, ImageFilter

PLUGIN = {"id": "god_rays", "name": PLUGIN_NAME, "version": PLUGIN_VERSION,
          "api": 2, "author": PLUGIN_AUTHOR,
          "description": "把高光沿一个方向拖成光束，模拟逆光丁达尔效应",
          "network": False, "writes_files": False}

PARAMS = [
    {"key": "threshold", "label": "取光门槛", "type": "slider",
     "min": 50, "max": 98, "default": 86, "step": 2},
    {"key": "length", "label": "光束长度", "type": "slider",
     "min": 20, "max": 220, "default": 110, "step": 10},
    {"key": "angle", "label": "角度", "type": "slider",
     "min": -60, "max": 60, "default": 14, "step": 2},
    {"key": "power", "label": "强度", "type": "slider",
     "min": 10, "max": 100, "default": 55, "step": 5},
]


def _beam(src, steps, dx, dy):
    """把亮部沿 (dx,dy) 累加成光束：多次平移取较亮者。"""
    acc = src.copy()
    for i in range(1, steps + 1):
        shifted = ImageChops.offset(src, int(dx * i), int(dy * i))
        acc = ImageChops.lighter(acc, shifted)
    return acc


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
        work = rgb.resize((max(1, int(w * scale)), max(1, int(h * scale))),
                          Image.BILINEAR)
    else:
        work = rgb
    ww, wh = work.size

    # 1) 取亮部
    thr = int(255 * float(p.get("threshold", 86)) / 100.0)
    gray = work.convert("L")
    bright = gray.point(lambda v: 255 if v >= thr else 0)
    bright = bright.filter(ImageFilter.MaxFilter(3))
    light = Image.composite(work, Image.new("RGB", (ww, wh), (0, 0, 0)), bright)

    # 2) 沿角度拖出光束
    ang = math.radians(float(p.get("angle", 14)))
    length = float(p.get("length", 110)) * (scale or 1.0)
    steps = 14
    dx = math.cos(ang) * (length / steps)
    dy = math.sin(ang) * (length / steps)
    beam = _beam(light, steps, dx, dy)
    beam = beam.filter(ImageFilter.GaussianBlur(max(1.0, 3.0 * (scale or 1.0))))

    # 3) 滤色叠加
    k = float(p.get("power", 55)) / 100.0
    beam = ImageEnhance.Brightness(beam).enhance(0.4 + 1.2 * k)
    out = ImageChops.screen(work, beam)

    if scale != 1.0:
        out = out.resize((w, h), Image.BICUBIC)
    if alpha is not None:
        out = out.convert("RGBA")
        out.putalpha(alpha)
    return out
