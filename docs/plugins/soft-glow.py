# -*- coding: utf-8 -*-
"""柔光（Soft Glow）：让高光轻微溢出，人像与逆光场景更柔。

官方清单插件。PARAMS 三个滑杆，run() 只返回新图，不改传入对象。
"""
import numpy as np
from PIL import Image, ImageFilter

PLUGIN = {
    "id": "soft-glow",
    "name": "柔光",
    "version": "1.0",
    "api": 2,
    "author": "Prism",
    "description": {"zh": "高光溢出 + 轻微模糊叠加，人像与逆光更柔和", "en": "Highlight bloom with a soft blur overlay; gentler portraits and backlight", "ja": "ハイライトをにじませて柔らかく。人物や逆光がやさしくなります"},
    "network": False,
    "writes_files": False,
}

PARAMS = [
    {"key": "amount", "label": {"zh": "强度", "en": "Strength", "ja": "強さ"}, "type": "slider",
     "min": 0, "max": 100, "default": 45, "step": 5},
    {"key": "radius", "label": {"zh": "半径", "en": "Radius", "ja": "半径"}, "type": "slider",
     "min": 1, "max": 40, "default": 18, "step": 1},
    {"key": "threshold", "label": {"zh": "高光门槛", "en": "Highlight threshold", "ja": "ハイライトのしきい値"}, "type": "slider",
     "min": 0, "max": 100, "default": 55, "step": 5},
]


def run(img, **params):
    amount = max(0.0, min(100.0, float(params.get("amount", 45)))) / 100.0
    if amount <= 0:
        return img.copy()
    radius = max(0.5, min(60.0, float(params.get("radius", 18))))
    hold = max(0.0, min(100.0, float(params.get("threshold", 55)))) / 100.0

    rgb = img.convert("RGB")
    base = np.asarray(rgb, dtype=np.float32)
    lum = (0.299 * base[:, :, 0] + 0.587 * base[:, :, 1]
           + 0.114 * base[:, :, 2]) / 255.0
    # 只让高光参与，避免整张图发灰
    gate = np.clip((lum - hold) / max(0.05, 1.0 - hold), 0.0, 1.0)
    gate = (gate * gate * (3.0 - 2.0 * gate))[:, :, None]

    blurred = np.asarray(rgb.filter(ImageFilter.GaussianBlur(radius)),
                         dtype=np.float32)
    # screen 混合：高光溢出而不是简单叠加
    screen = 255.0 - (255.0 - base) * (255.0 - blurred) / 255.0
    mixed = base + (screen - base) * gate * amount
    out = np.clip(mixed, 0, 255).astype(np.uint8)

    res = Image.fromarray(out, "RGB")
    if img.mode == "L":
        return res.convert("L")
    if img.mode == "RGBA":
        res = res.convert("RGBA")
        res.putalpha(img.getchannel("A"))
    return res
