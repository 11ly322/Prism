# -*- coding: utf-8 -*-
"""双色调（Duotone）：按明度把画面映射到两种颜色之间。

官方清单插件。颜色用预设名而不是色值，省得写颜色选择控件。
"""
import numpy as np
from PIL import Image

PLUGIN = {
    "id": "duotone",
    "name": "双色调",
    "version": "1.0",
    "api": 2,
    "author": "Prism",
    "description": {"zh": "明度映射到暗部/亮部两种颜色，做海报与封面配色", "en": "Maps luminance between two colors; good for posters and covers", "ja": "明度を 2 色にマッピング。ポスターや表紙の配色に"},
    "network": False,
    "writes_files": False,
}

DARK = {
    "深蓝": (22, 34, 74),
    "暗红": (74, 22, 30),
    "墨绿": (18, 56, 44),
    "紫夜": (44, 24, 70),
    "黑": (12, 12, 14),
}
LIGHT = {
    "米白": (245, 238, 222),
    "浅橙": (250, 214, 165),
    "天蓝": (188, 224, 245),
    "薄荷": (205, 240, 222),
    "白": (255, 255, 255),
}
# 选项值仍是中文（run 里按值查表），只是界面上按语言显示 label
DARK_LABELS = {
    "深蓝": {"zh": "深蓝", "en": "Deep blue", "ja": "深い青"},
    "暗红": {"zh": "暗红", "en": "Dark red", "ja": "暗い赤"},
    "墨绿": {"zh": "墨绿", "en": "Ink green", "ja": "墨緑"},
    "紫夜": {"zh": "紫夜", "en": "Night purple", "ja": "夜紫"},
    "黑": {"zh": "黑", "en": "Black", "ja": "黒"},
}
LIGHT_LABELS = {
    "米白": {"zh": "米白", "en": "Cream", "ja": "生成り"},
    "浅橙": {"zh": "浅橙", "en": "Light orange", "ja": "薄橙"},
    "天蓝": {"zh": "天蓝", "en": "Sky blue", "ja": "空色"},
    "薄荷": {"zh": "薄荷", "en": "Mint", "ja": "ミント"},
    "白": {"zh": "白", "en": "White", "ja": "白"},
}

PARAMS = [
    {"key": "dark", "label": {"zh": "暗部颜色", "en": "Shadow color", "ja": "暗部の色"}, "type": "select",
     "options": [{"value": k, "label": DARK_LABELS[k]} for k in DARK],
     "default": "深蓝"},
    {"key": "light", "label": {"zh": "亮部颜色", "en": "Highlight color", "ja": "明部の色"}, "type": "select",
     "options": [{"value": k, "label": LIGHT_LABELS[k]} for k in LIGHT],
     "default": "米白"},
    {"key": "amount", "label": {"zh": "强度", "en": "Strength", "ja": "強さ"}, "type": "slider",
     "min": 0, "max": 100, "default": 100, "step": 5},
]


def run(img, **params):
    amount = max(0.0, min(100.0, float(params.get("amount", 100)))) / 100.0
    if amount <= 0:
        return img.copy()
    lo = np.array(DARK.get(str(params.get("dark")), DARK["深蓝"]), np.float32)
    hi = np.array(LIGHT.get(str(params.get("light")), LIGHT["米白"]), np.float32)

    rgb = img.convert("RGB")
    a = np.asarray(rgb, dtype=np.float32)
    lum = (0.299 * a[:, :, 0] + 0.587 * a[:, :, 1] + 0.114 * a[:, :, 2]) / 255.0
    t = lum[:, :, None]
    duo = lo + (hi - lo) * t
    out = np.clip(a + (duo - a) * amount, 0, 255).astype(np.uint8)

    res = Image.fromarray(out, "RGB")
    if img.mode == "L":
        return res.convert("L")
    if img.mode == "RGBA":
        res = res.convert("RGBA")
        res.putalpha(img.getchannel("A"))
    return res
